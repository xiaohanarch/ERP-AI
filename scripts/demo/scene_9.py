#!/usr/bin/env python3
"""第 9 幕：Message 扩展 —— 租户消息订阅与隔离投递（观点 14 的后半句）。

场景（业务驱动）：华东制造（T-EAST）想让自己租户侧的系统实时响应
「发票被阻断」——推给自己的合规监控。SaaS 平台不开放核心改造，租户通过
**消息订阅**扩展：注册（topic + webhook + 签名密钥），平台把领域事件
按（租户 × topic）隔离投递出平台。与形态④（事件触发平台内 Agent）互补：
一个是事件进 Agent，一个是事件出平台。

链路：Java outbox（republish 重投触发）→ hub 事件线程（形态④消费 + 通知）
→ 网关消息分发（租户隔离 + HMAC-SHA256 签名）→ 租户 webhook 验签消费。

断言：投递到达与载荷正确 / HMAC 验签通过 / 投递审计留痕 /
T-UNI 订阅收不到 T-EAST 事件（租户隔离）/ 吊销即停投 / 同事件双路消费
（EVENT_DIAG 通知 + webhook 投递）。

用法: python scripts/demo/scene_9.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402

TOPIC = "ap.invoice.blocked"
EVENT_KEY = "ap.invoice.blocked:INV-A-001"
SECRETS = {"east": "east-hook-secret-demo", "uni": "uni-hook-secret-demo"}


def _make_receiver() -> tuple[ThreadingHTTPServer, list]:
    """本机 webhook 接收器（租户侧系统的替身）：记录投递并返回 (server, records)。"""
    records: list[dict] = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 —— http.server 约定
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            records.append({"path": self.path, "headers": dict(self.headers),
                            "raw": raw, "body": json.loads(raw or b"{}")})
            payload = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):  # 精简日志
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.serve_forever, daemon=True, name="webhook-receiver").start()
    return server, records


def _verify_signature(rec: dict, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), rec["raw"], hashlib.sha256).hexdigest()
    return rec["headers"].get("X-ERP-Signature") == f"sha256={expected}"


def _register(tenant: str, side: str, port: int) -> str:
    resp = C.gw_post("/gw/subscriptions", {
        "tenantId": tenant, "topic": TOPIC,
        "endpointUrl": f"http://host.docker.internal:{port}/{side}",
        "secret": SECRETS[side]})
    return resp["subscriptionId"]


def _cleanup() -> list[str]:
    """清理该 topic 的历史活跃订阅（含崩溃残留的死端点；保证场景可重跑且隔离断言无污染）。"""
    revoked = []
    for sub in C.gw_get("/gw/subscriptions").get("subscriptions", []):
        if sub["status"] == "ACTIVE" and sub["topic"] == TOPIC:
            C.gw_post(f"/gw/subscriptions/{sub['subscriptionId']}/revoke", {})
            revoked.append(sub["subscriptionId"])
    return revoked


def _republish() -> None:
    resp = httpx.post(f"{C.JAVA}/internal/events/republish",
                      headers={"X-Internal-Secret": C.INTERNAL_SECRET},
                      json={"eventKey": EVENT_KEY}, timeout=15)
    resp.raise_for_status()


def _wait_records(records: list, want: int, timeout: float = 90.0) -> int:
    # 90s：事件诊断含 live 模型归因摘要（GLM-5.3 真实调用，约 15-40s）；
    # mock 模式瞬时返回，不受影响
    deadline = time.time() + timeout
    while time.time() < deadline and len(records) < want:
        time.sleep(0.5)
    return len(records)


def main() -> int:
    print("=== 第 9 幕：Message 扩展（租户消息订阅与隔离投递） ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_9] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 9 幕")
    east_srv, east_rec = _make_receiver()
    uni_srv, uni_rec = _make_receiver()
    east_port = east_srv.server_address[1]
    uni_port = uni_srv.server_address[1]
    leftovers = _cleanup()

    # ---- 1) 注册双租订阅（T-EAST / T-UNI 各一个 webhook） ----
    print("── 注册订阅：T-EAST 与 T-UNI 各自的 webhook")
    east_sub = _register("T-EAST", "east", east_port)
    uni_sub = _register("T-UNI", "uni", uni_port)
    subs = C.gw_get("/gw/subscriptions").get("subscriptions", [])
    print(f"  订阅：{east_sub}（T-EAST -> :{east_port}/east）/ {uni_sub}（T-UNI -> :{uni_port}/uni）")
    ck.add("双租订阅注册成功（topic=ap.invoice.blocked）",
           any(s["subscriptionId"] == east_sub for s in subs)
           and any(s["subscriptionId"] == uni_sub for s in subs),
           f"清史 {len(leftovers)} 条")

    # ---- 2) 事件重投 -> 双路消费（平台内 Agent + 租户 webhook） ----
    print("── 事件重投：INV-A-001 阻断事件走首发同链路")
    t0 = time.time()
    _republish()
    got = _wait_records(east_rec, 1)
    latency = time.time() - t0
    print(f"  T-EAST webhook {got} 条（{latency:.1f}s 内）；T-UNI webhook {len(uni_rec)} 条")
    if not east_rec:
        ck.add("T-EAST webhook 收到投递", False, f"{latency:.0f}s 内未收到（hub 轮询 5s + 事件处理）")
    else:
        rec = east_rec[0]
        body = rec["body"]
        ck.add("T-EAST webhook 收到投递（载荷正确）",
               body.get("invoiceNo") == "INV-A-001" and body.get("tenantId") == "T-EAST"
               and body.get("eventType") == TOPIC and body.get("redelivered") is True
               and body.get("deliveryId", "").startswith("dlv-"),
               json.dumps({k: body.get(k) for k in ("invoiceNo", "tenantId", "eventType",
                                                    "redelivered", "deliveryId")},
                          ensure_ascii=False))
        ck.add("投递携带 HMAC-SHA256 签名（租户侧验签通过）",
               _verify_signature(rec, SECRETS["east"]),
               f"X-ERP-Signature={rec['headers'].get('X-ERP-Signature', '')[:24]}…")

    time.sleep(3)  # 隔离断言的观察窗：T-UNI 若被误投，3 秒内必达
    ck.add("租户隔离：T-UNI 订阅收不到 T-EAST 事件", len(uni_rec) == 0,
           f"uni 收到 {len(uni_rec)} 条")

    audit = C.gw_get("/internal/audit", {"limit": 80})
    dispatch_rows = [r for r in audit.get("items", [])
                     if r.get("action") == "event.dispatch" and str(r.get("ts", "")) >=
                     time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 - 2))]
    ok_rows = [r for r in dispatch_rows if r.get("outcome") == "SUCCESS"]
    ck.add("投递审计留痕（event.dispatch SUCCESS）", len(ok_rows) >= 1,
           f"时间窗内 {len(dispatch_rows)} 条（成功 {len(ok_rows)}）")

    t1 = C.login("lisi")
    notif = httpx.get(f"{C.GW}/gw/notifications",
                      headers={"Authorization": f"Bearer {t1}"}, timeout=15).json()
    kinds = [n.get("kind") for n in notif.get("items", [])]
    ck.add("同事件双路消费（形态④ EVENT_DIAG 通知同时产生）", "EVENT_DIAG" in kinds,
           str(kinds[:5]))

    # ---- 3) 吊销即停投 ----
    print("── 吊销订阅：对后续投递即时生效")
    C.gw_post(f"/gw/subscriptions/{east_sub}/revoke", {})
    _republish()
    time.sleep(12)  # 覆盖 hub 轮询周期（5s）+ 事件处理
    ck.add("吊销后不再投递（生命周期即边界）", len(east_rec) == got,
           f"吊销前 {got} 条 / 吊销后仍 {len(east_rec)} 条")

    # ---- 收尾（可重跑）----
    for sid in (east_sub, uni_sub):
        try:
            C.gw_post(f"/gw/subscriptions/{sid}/revoke", {})
        except Exception:  # noqa: BLE001 —— 已吊销则忽略
            pass
    east_srv.shutdown()
    uni_srv.shutdown()

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
