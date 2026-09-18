"""定时调度线程：周期触发 ap-batch 全量阻断筛查（形态⑤：Scheduler 触发 Agent）。

与 events.py（形态④ 事件触发）同为无用户会话的代表执行，差别仅在触发源：
  - 事件 = 存量域 outbox（业务事实发生时）；
  - 定时 = 周期到期（运营例行任务，如定时阻断筛查摘要）。

设计要点：
  - 定时例程钉定 X-Model-Mode: mock —— 与评测同策略：确定性、零 live 配额消耗
    （模型模式钉定机制本身即本项目的架构能力，此处是第三个应用场景）；
  - 结果与上次比较有变化才推送通知（首次运行必通知），避免周期性打扰；
  - 每次运行全程留痕：审计（网关，agent=ap-batch）+ 解析记录（hub resolution_log）
    + 成本台账；演示/验证可经 hub POST /internal/scheduler/run 手动触发同一执行路径。
"""
from __future__ import annotations

import threading
import time

from hub import config, db, gw
from hub.graphs import batch
from hub.graphs.agents import agent_for
from hub.sdk import run_graph

TENANT = "T-EAST"
USER = "lisi"
MESSAGE = "定时筛查：列出当前数据权限范围内全部被阻断的发票，并统计主要原因分布"

_last_digest: str | None = None


def _digest(answer: str) -> str:
    """变化检测摘要：答案文本去空白（名单或计数变化即可检出）。"""
    return "".join((answer or "").split())


def run_once(manual: bool = False) -> dict:
    """执行一次定时筛查（manual=True 表示演示/验证手动触发，同样留痕）。"""
    global _last_digest
    thread_id = f"sched-{int(time.time())}"
    state_in = {
        "message": MESSAGE, "user": USER, "tenant": TENANT,
        "trace": thread_id, "conversation_id": thread_id,
        "model_mode": "mock",  # 定时例程确定性通道（与评测同策略，见模块注释）
    }
    graph = batch.build()
    values, _ = run_graph(graph, state_in, thread_id)
    answer = values.get("answer", "")
    digest = _digest(answer)
    changed = _last_digest is None or digest != _last_digest
    _last_digest = digest
    db.log_resolution(thread_id, "ap.batch", TENANT,
                      {"scene": "ap.batch", "trigger": "scheduler",
                       "agent": agent_for(batch.AGENT, TENANT),
                       "manual": manual, "modelMode": "mock"})
    notified = False
    if changed:
        gw.push_notification(TENANT, USER, kind="scheduled_batch",
                             title="定时筛查：阻断发票摘要有更新",
                             body=answer[:400])
        notified = True
    print(f"[scheduler] {'手动' if manual else '定时'}筛查完成"
          f"（{'有变化，已通知' if notified else '无变化，不重复通知'}）", flush=True)
    return {"answer": answer, "changed": changed, "notified": notified,
            "conversationId": thread_id}


def start() -> None:
    """启动定时调度线程（SCHEDULER_ENABLED!=1 时不启动）。"""
    if not config.settings.scheduler_enabled:
        print("[scheduler] 未启用（SCHEDULER_ENABLED!=1）", flush=True)
        return

    def _loop() -> None:
        time.sleep(8)  # 启动等待：图装配与数据库就绪（与 events.py 一致）
        while True:
            try:
                run_once()
            except Exception as e:  # noqa: BLE001 —— 调度线程不允许退出
                print(f"[scheduler] 定时筛查异常（将继续重试）：{e}", flush=True)
            time.sleep(config.settings.scheduler_interval)

    threading.Thread(target=_loop, daemon=True, name="scheduled-agent").start()
