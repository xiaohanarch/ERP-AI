"""事件订阅线程：轮询存量域 outbox（ap.invoice.blocked）-> 无头诊断 -> 通知。

形态④（事件触发 Agent）：无用户会话，代表 event-diag 代理执行，
经网关 exchange（后端凭据）换 T2 后调 BO 工具，全程留痕。
"""
from __future__ import annotations

import json
import threading
import time

import httpx

from hub import config, db, gw
from hub.graphs import eventdiag
from hub.sdk import run_graph

_acked: set[int] = set()


def start() -> None:
    threading.Thread(target=_loop, daemon=True, name="event-subscriber").start()


def _loop() -> None:
    # 启动等待：图装配与数据库就绪
    time.sleep(5)
    graph = eventdiag.build()
    while True:
        try:
            events = _poll()
            ids = []
            for ev in events:
                if _handle(ev, graph):
                    ids.append(ev["id"])
            if ids:
                _ack(ids)
        except Exception as e:  # noqa: BLE001 —— 订阅线程不允许退出
            print(f"[events] 订阅循环异常（将继续重试）：{e}", flush=True)
        time.sleep(5)


def _poll() -> list[dict]:
    resp = httpx.get(f"{config.settings.erp_ap_base}/internal/events?limit=5",
                     headers={"X-Internal-Secret": config.settings.internal_secret},
                     timeout=10)
    resp.raise_for_status()
    return resp.json().get("events", [])


def _ack(ids: list[int]) -> None:
    httpx.post(f"{config.settings.erp_ap_base}/internal/events/ack",
               headers={"X-Internal-Secret": config.settings.internal_secret},
               json={"ids": ids}, timeout=10)


def _handle(ev: dict, graph) -> bool:
    """处理单条事件。返回 True 表示可 ack。"""
    ev_id = ev.get("id")
    if ev_id in _acked:
        return True
    try:
        payload = json.loads(ev.get("payload_json") or "{}")
    except ValueError:
        return True  # 无法解析的事件直接 ack，避免堵塞队列
    if ev.get("event_type") != "ap.invoice.blocked":
        _acked.add(ev_id)
        return True

    tenant = payload.get("tenantId")
    invoice_no = payload.get("invoiceNo")
    thread_id = f"event-{ev.get('event_key') or ev_id}"
    try:
        state_in = {
            "message": f"事件触发：发票 {invoice_no} 被阻断", "invoice_no": invoice_no,
            "user": "lisi", "tenant": tenant, "trace": f"evt-{ev_id}",
            "conversation_id": thread_id, "result": payload,
        }
        values, _ = run_graph(graph, state_in, thread_id)
        answer = values.get("answer", "")
        db.log_resolution(thread_id, "ap.event", tenant,
                          {"scene": "ap.event", "trigger": "ap.invoice.blocked",
                           "invoiceNo": invoice_no, "headless": True})
        gw.push_notification(tenant, "lisi", kind="event_diag", invoice_no=invoice_no,
                             summary=answer[:300])
        print(f"[events] 无头诊断完成：{invoice_no}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[events] 无头诊断失败（{invoice_no}）：{e}", flush=True)
    _acked.add(ev_id)
    return True
