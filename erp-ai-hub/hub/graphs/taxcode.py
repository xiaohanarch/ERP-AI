"""ap.taxcode 场景图：税码建议与补全（写路径样板：interrupt 审批断点 + 恢复）。

节点链：suggest（模型建议） -> request_approval（网关强制审批：GW.APPROVAL_REQUIRED）
        -> approval_gate（interrupt 挂起，唤醒值 = {oneTimeToken, rejected}）
        -> apply（携 OT 重发，幂等键按步骤 = 业务键+审批单号） -> END

关键设计：网关调用与 interrupt 分属不同节点 —— 恢复时只重跑 approval_gate
（interrupt 立即返回唤醒值，不再打网关），不会重复创建审批任务。
"""
from __future__ import annotations

from datetime import date

from hub import gw
from hub.graphs.state import GraphState, contract_messages, ctx_of
from hub.graphs.agents import agent_for
from hub.sdk import build_graph, interrupt

AGENT = "ap-copilot"
SCENE = "ap.taxcode"


def _current_period() -> str:
    return date.today().strftime("%Y-%m")


def suggest(state: GraphState) -> dict:
    action = gw.ask_model(SCENE, contract_messages(SCENE, state["message"]), ctx_of(state))
    if action.get("intent") != "suggest_tax_code" or not action.get("invoiceNo"):
        return {"intent": "clarify",
                "answer": action.get("reply", "请提供需要补全税码的发票号（如 INV-A-003）。")}
    suggestion = {
        "invoiceNo": action["invoiceNo"],
        "taxCode": action.get("taxCode", "CN-VAT-13"),
        "reason": action.get("reason", "供应商所在地常用税码建议"),
        "reply": action.get("reply", ""),
    }
    return {"intent": "suggest_tax_code", "invoice_no": action["invoiceNo"],
            "suggestion": suggestion, "tool_calls": []}


def _route(state: GraphState) -> str:
    return "request_approval" if state.get("intent") == "suggest_tax_code" else "done"


def request_approval(state: GraphState) -> dict:
    """发起税码变更申请：网关对不可逆操作强制审批（返回 GW.APPROVAL_REQUIRED + approval_id）。"""
    s = state["suggestion"]
    args = {"invoiceNo": s["invoiceNo"], "taxCode": s["taxCode"],
            "reason": s["reason"], "accountPeriod": _current_period()}
    # 业务幂等基础键：随审批任务留痕；apply 步骤在其上追加审批单号（按任务步骤生成）
    idem_key = f"taxcode:{s['invoiceNo']}:{s['taxCode']}:{args['accountPeriod']}"
    context = {
        "idempotencyKey": idem_key,
        "rationale": s["reason"],
        "impact": f"将发票 {s['invoiceNo']} 的税码变更为 {s['taxCode']}（不可逆写操作，"
                  f"落库至税码变更记录并留痕）",
        "snapshot": {"invoiceNo": s["invoiceNo"], "suggestedTaxCode": s["taxCode"],
                     "accountPeriod": args["accountPeriod"], "reason": s["reason"],
                     "invoiceAmount": None},
    }
    t2 = gw.exchange(agent_for(AGENT, state["tenant"]), SCENE, ["ap.invoice.applyTaxCode"],
                     state["user"], state["tenant"])
    try:
        result = gw.mcp_call(t2, "ap.invoice.applyTaxCode", args, context)
        return {"approval_result": "applied", "result": result,
                "tool_calls": [{"tool": "ap.invoice.applyTaxCode", "arguments": args, "ok": True}],
                "answer": _compose_applied(result)}
    except gw.GwToolError as e:
        if e.code == "GW.APPROVAL_REQUIRED":
            approval = {"approvalId": e.remediation.get("approval_id"),
                        "expiresIn": e.remediation.get("expires_in") or 1800}
            return {"approval": approval, "pending_args": args, "pending_context": context,
                    "approval_result": "pending",
                    "tool_calls": [{"tool": "ap.invoice.applyTaxCode", "arguments": args,
                                    "ok": False, "error": "GW.APPROVAL_REQUIRED"}]}
        return {"tool_calls": [{"tool": "ap.invoice.applyTaxCode", "arguments": args,
                                "ok": False, "error": e.code}],
                "error": {"code": e.code, "message": e.message},
                "answer": f"税码申请提交失败：{e.code} —— {e.message}"}


def approval_gate(state: GraphState) -> dict:
    """审批门：首次执行挂起（载荷 = 审批三要素展示）；恢复时返回唤醒值。"""
    payload = {
        "type": "approval_required",
        "approvalId": state["approval"]["approvalId"],
        "suggestion": state["suggestion"],
        "rationale": state["pending_context"]["rationale"],
        "impact": state["pending_context"]["impact"],
        "expiresIn": state["approval"].get("expiresIn"),
    }
    decision = interrupt(payload)
    return {"ot": decision if isinstance(decision, dict) else {"oneTimeToken": decision}}


def apply(state: GraphState) -> dict:
    """审批通过后携 OT 重发；拒绝则取消。"""
    decision = state.get("ot") or {}
    args, context = state["pending_args"], dict(state["pending_context"])
    if decision.get("rejected") or not decision.get("oneTimeToken"):
        return {"approval_result": "rejected",
                "answer": "审批被拒绝，税码变更未执行。原申请已留痕，可修正后重新发起。"}
    context["approvalToken"] = decision["oneTimeToken"]
    # 幂等键按任务步骤生成（业务键 + 审批单号）：同步骤的网络重传命中网关短窗；
    # 跨审批的再次发起不受短窗影响，由存量域业务幂等表返回首次执行结果。
    context["idempotencyKey"] = f"{context['idempotencyKey']}:{state['approval']['approvalId']}"
    t2 = gw.exchange(agent_for(AGENT, state["tenant"]), SCENE, ["ap.invoice.applyTaxCode"],
                     state["user"], state["tenant"])
    try:
        result = gw.mcp_call(t2, "ap.invoice.applyTaxCode", args, context)
    except gw.GwToolError as e:
        return {"approval_result": "failed",
                "error": {"code": e.code, "message": e.message},
                "tool_calls": [{"tool": "ap.invoice.applyTaxCode", "arguments": args,
                                "ok": False, "error": e.code}],
                "answer": f"税码落库失败：{e.code} —— {e.message}"}
    return {"approval_result": "applied", "result": result,
            "tool_calls": [{"tool": "ap.invoice.applyTaxCode", "arguments": args, "ok": True}],
            "answer": _compose_applied(result)}


def _compose_applied(result: dict) -> str:
    return (f"税码变更已完成：发票 {result.get('invoiceNo')} 税码 {result.get('previousTaxCode') or '（空）'}"
            f" -> {result.get('newTaxCode')}。\n审批人：{result.get('decidedBy')}，"
            f"审批单号：{result.get('approvalRef')}，变更记录：{result.get('changeId')}，"
            f"幂等重放：{'是' if result.get('idempotentReplay') else '否'}。")


def done(state: GraphState) -> dict:
    return {}


def build():
    return build_graph(
        GraphState,
        nodes=[("suggest", suggest), ("request_approval", request_approval),
               ("approval_gate", approval_gate), ("apply", apply), ("done", done)],
        edges=[("START", "suggest"), ("request_approval", "approval_gate"),
               ("approval_gate", "apply"), ("apply", "END"), ("done", "END")],
        conditional={"suggest": (_route, ["request_approval", "done"])})
