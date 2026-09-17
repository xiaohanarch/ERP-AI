"""ap.batch 场景图：阻断发票批量筛查（读侧，含大额口径与数据权限披露）。"""
from __future__ import annotations

from hub import gw
from hub.graphs.state import GraphState, ctx_of, fmt_amount
from hub.graphs.agents import agent_for
from hub.sdk import build_graph

AGENT = "ap-batch"
SCENE = "ap.batch"


def classify(state: GraphState) -> dict:
    action = gw.ask_model(SCENE, [{"role": "user", "content": state["message"]}], ctx_of(state))
    return {"intent": action.get("intent", "batch_screen"),
            "tool_calls": [], "error": None,
            "answer": action.get("reply") if action.get("intent") == "clarify" else None}


def _route(state: GraphState) -> str:
    return "screen" if state.get("intent") == "batch_screen" else "done"


def screen(state: GraphState) -> dict:
    user, tenant = state["user"], state["tenant"]
    message = state.get("message", "")
    big = ("大额" in message) or ("风险" in message)

    tools = ["ap.invoice.listBlocked", "semantic.metric.get"]
    t2 = gw.exchange(agent_for(AGENT, tenant), SCENE, tools, user, tenant)
    calls = []

    threshold = None
    source = None
    if big:
        m = gw.mcp_call(t2, "semantic.metric.get", {"metric": "large_risk_amount"})
        caliber = (m.get("result") or {}).get("caliber") or {}
        threshold, source = caliber.get("threshold"), caliber.get("thresholdSource")
        calls.append({"tool": "semantic.metric.get", "arguments": {"metric": "large_risk_amount"},
                      "ok": True})

    arguments = {"pageSize": 100}
    if threshold is not None:
        arguments["minAmountCny"] = threshold
    page = gw.mcp_call(t2, "ap.invoice.listBlocked", arguments)
    calls.append({"tool": "ap.invoice.listBlocked", "arguments": arguments, "ok": True})

    items = page.get("items", [])
    info = page.get("pageInfo") or {}
    filtered = page.get("filteredByDimension") or {}
    dims = "、".join(filtered.get("dimensions") or []) or "无"

    # 阻断原因分布
    reason_count: dict[str, int] = {}
    for it in items:
        for r in it.get("blockedReasons") or []:
            reason_count[r] = reason_count.get(r, 0) + 1
    dist = "、".join(f"{k}×{v}" for k, v in
                     sorted(reason_count.items(), key=lambda kv: -kv[1])) or "无"

    lines = []
    if threshold is not None:
        lines.append(f"按本租户大额风险口径（阈值 {fmt_amount(threshold)} 元，来源：{source}）"
                     f"筛选阻断发票。")
    lines.append(f"当前数据权限范围内共有 {info.get('total', len(items))} 张被阻断的发票"
                 f"（本页返回 {len(items)} 张；数据权限过滤维度：{dims}）。")
    lines.append(f"阻断原因分布：{dist}。")
    for it in items[:10]:
        lines.append(f"  - {it.get('invoiceNo')}：{fmt_amount(it.get('amountCny'))} 元"
                     f"（{it.get('supplier', '-')}）")
    if info.get("truncated"):
        lines.append("（单页截断：可翻页或缩小范围继续筛查）")
    if info.get("nextCursor"):
        lines.append("提示：结果超出一页，可继续翻页获取剩余。")
    return {"tool_calls": calls, "result": page, "answer": "\n".join(lines)}


def done(state: GraphState) -> dict:
    return {}


def build():
    return build_graph(
        GraphState,
        nodes=[("classify", classify), ("screen", screen), ("done", done)],
        edges=[("START", "classify"), ("screen", "END"), ("done", "END")],
        conditional={"classify": (_route, ["screen", "done"])})
