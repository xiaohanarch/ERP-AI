"""ap.event 场景图：事件触发无头诊断（形态④，无用户交互）。

由 events.py 订阅线程驱动：ap.invoice.blocked -> 工具取证（确定性）->
模型归因摘要（经模型网关真实调用 LLM，基于取证发现、不发明事实；
模型失败回落确定性拼装——后台线程不允许因模型中断）-> 通知相关人。
"""
from __future__ import annotations

from hub import gw
from hub.graphs.state import GraphState, contract_messages, ctx_of, fmt_amount
from hub.sdk import build_graph

AGENT = "event-diag"
SCENE = "ap.event"


def diagnose_event(state: GraphState) -> dict:
    inv = state.get("invoice_no") or ""
    event = state.get("result") or {}
    user = state.get("user") or "lisi"
    tenant = state.get("tenant")
    t2 = gw.exchange(AGENT, SCENE,
                     ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail"], user, tenant)
    calls = []
    try:
        v = gw.mcp_call(t2, "ap.invoice.checkValidation", {"invoiceNo": inv})
        calls.append({"tool": "ap.invoice.checkValidation", "arguments": {"invoiceNo": inv},
                      "ok": True})
    except gw.GwToolError as e:
        return {"tool_calls": [{"tool": "ap.invoice.checkValidation",
                                "arguments": {"invoiceNo": inv}, "ok": False, "error": e.code}],
                "error": {"code": e.code, "message": e.message},
                "answer": f"[事件诊断] 发票 {inv} 诊断失败：{e.code} —— {e.message}"}

    # 确定性证据行（通知里永远有可核对的底账，摘要只是把它讲成人话）
    lines = [f"[事件诊断] 发票 {inv} 已阻断（事件 {event.get('eventType', 'ap.invoice.blocked')}，"
             f"金额 {fmt_amount(event.get('amountCny'))} 元，组织 {event.get('org', '-')}）。"]
    for f in v.get("findings", []):
        sev = {"BLOCK": "阻断", "WARN": "警告", "INFO": "提示"}[f.get("severity", "INFO")]
        lines.append(f"  - [{sev}] {f.get('ruleId')}：{f.get('message')}")
    completeness = v.get("completeness") or {}
    if completeness.get("full") is False:
        skipped = "、".join(completeness.get("skippedRuleGroups") or [])
        lines.append(f"  ⚠ 校验不完整：{completeness.get('reason', '原因未知')}"
                     f"（跳过规则组：{skipped or '-'}）")

    # 模型归因摘要：经模型网关真实调用 LLM（live 模式下为 GLM-5.3）；
    # 依据上面的取证发现讲人话，契约约束「不发明未提及的事实」；
    # 后台线程不允许因模型失败而中断——异常回落确定性拼装
    try:
        action = gw.ask_model(SCENE, contract_messages(SCENE, "\n".join(lines)), ctx_of(state))
        summary = str(action.get("summary") or action.get("reply") or "").strip()
    except Exception:  # noqa: BLE001 —— 模型不可达/超时/解析失败：回落确定性结论
        summary = ""
    if summary:
        lines.insert(1, f"  归因摘要：{summary}")

    lines.append("（本诊断由事件自动触发，无用户会话；结果已推送通知）")
    return {"tool_calls": calls, "result": v, "answer": "\n".join(lines)}


def build():
    return build_graph(
        GraphState,
        nodes=[("diagnose_event", diagnose_event)],
        edges=[("START", "diagnose_event"), ("diagnose_event", "END")])
