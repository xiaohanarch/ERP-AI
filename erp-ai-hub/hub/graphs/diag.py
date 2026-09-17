"""ap.diag 场景图：发票阻断归因诊断（读侧样板）。

节点：classify（模型动作） -> diagnose（校验 + 匹配下钻）/ large_risk（口径筛查）-> END
"""
from __future__ import annotations

from hub import gw
from hub.graphs.state import ctx_of, fmt_amount
from hub.sdk import build_graph
from hub.graphs.agents import agent_for
from hub.graphs.state import GraphState

AGENT = "ap-copilot"
SCENE = "ap.diag"


def classify(state: GraphState) -> dict:
    action = gw.ask_model(SCENE, [{"role": "user", "content": state["message"]}], ctx_of(state))
    out = {"intent": action.get("intent", "clarify"),
           "tool_calls": [], "error": None}
    if action.get("intent") in ("diagnose", "event_diag"):
        out["invoice_no"] = action.get("invoiceNo")
    if action.get("intent") == "clarify":
        out["answer"] = action.get("reply", "请提供发票号（如 INV-A-001），或描述要筛查的范围。")
    return out


def route(state: GraphState) -> str:
    if state.get("intent") == "diagnose" and state.get("invoice_no"):
        return "diagnose"
    if state.get("intent") == "large_risk":
        return "large_risk"
    return "done"


def diagnose(state: GraphState) -> dict:
    user, tenant, inv = state["user"], state["tenant"], state["invoice_no"]
    t2 = gw.exchange(agent_for(AGENT, tenant), SCENE,
                     ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail"], user, tenant)
    calls = []
    try:
        v = gw.mcp_call(t2, "ap.invoice.checkValidation", {"invoiceNo": inv})
        calls.append({"tool": "ap.invoice.checkValidation",
                      "arguments": {"invoiceNo": inv}, "ok": True})
    except gw.GwToolError as e:
        return {"tool_calls": [{"tool": "ap.invoice.checkValidation",
                                "arguments": {"invoiceNo": inv}, "ok": False, "error": e.code}],
                "error": {"code": e.code, "message": e.message},
                "answer": f"发票 {inv} 校验失败：{e.code} —— {e.message}"}

    match_detail = None
    if v.get("overallResult") == "BLOCKED" and any(
            f.get("ruleGroup") == "MATCH" for f in v.get("findings", [])):
        try:
            match_detail = gw.mcp_call(t2, "ap.invoice.getMatchDetail", {"invoiceNo": inv})
            calls.append({"tool": "ap.invoice.getMatchDetail",
                          "arguments": {"invoiceNo": inv}, "ok": True})
        except gw.GwToolError:
            pass  # 下钻失败不阻断主归因

    return {"tool_calls": calls, "result": v,
            "answer": _compose_diag(inv, v, match_detail)}


def _compose_diag(inv: str, v: dict, match_detail: dict | None) -> str:
    overall = v.get("overallResult", "UNKNOWN")
    label = {"PASSED": "通过", "WARNED": "警告", "BLOCKED": "阻断"}[overall]
    lines = [f"发票 {inv} 校验结果：{label}（规则集 {v.get('ruleSetVersion')}）"]
    summary = v.get("invoiceSummary") or {}
    if summary:
        lines.append(f"供应商：{summary.get('supplier', '-')}，金额：{fmt_amount(summary.get('amountCny'))} 元")
    findings = v.get("findings", [])
    if findings:
        lines.append("发现：")
        for f in findings:
            sev = {"BLOCK": "阻断", "WARN": "警告", "INFO": "提示"}[f.get("severity", "INFO")]
            lines.append(f"  - [{sev}] {f.get('ruleId')}：{f.get('message')}")
            rem = (f.get("remediation") or {})
            if rem.get("action"):
                lines.append(f"      建议：{rem['action']}")
    else:
        lines.append("未发现异常项。")

    completeness = v.get("completeness") or {}
    if completeness and completeness.get("full") is False:
        skipped = "、".join(completeness.get("skippedRuleGroups") or [])
        reason = completeness.get("reason") or "原因未知"
        lines.append(f"⚠ 校验不完整：{reason}（跳过规则组：{skipped or '-'}）。"
                     f"以上结论仅基于已执行的规则组，不代表整体无风险。")

    if match_detail and match_detail.get("lines"):
        lines.append(f"三单匹配差异下钻（PO {match_detail.get('poNo', '-')} / GR {match_detail.get('grNo', '-')}）：")
        for ln in match_detail["lines"]:
            diffs = "、".join(ln.get("findings") or []) or "无差异"
            lines.append(f"  - 行{ln.get('lineNo')} {ln.get('item', '')}："
                         f"发票数量 {fmt_amount(ln.get('invoiceQty'))} / 收货数量 {fmt_amount(ln.get('grQty'))}"
                         f"（{diffs}）")
    return "\n".join(lines)


def large_risk(state: GraphState) -> dict:
    """大额风险筛查：先取租户口径阈值（A0 叠加 + 来源取证），再按阈值筛阻断发票。"""
    user, tenant = state["user"], state["tenant"]
    t2 = gw.exchange(agent_for(AGENT, tenant), SCENE,
                     ["semantic.metric.get", "ap.invoice.listBlocked"], user, tenant)
    m = gw.mcp_call(t2, "semantic.metric.get", {"metric": "large_risk_amount"})
    caliber = (m.get("result") or {}).get("caliber") or {}
    meta = m.get("_meta") or {}
    threshold = caliber.get("threshold")
    source = caliber.get("thresholdSource") or "Standard 层默认"

    calls = [{"tool": "semantic.metric.get", "arguments": {"metric": "large_risk_amount"},
              "ok": True}]
    page = gw.mcp_call(t2, "ap.invoice.listBlocked",
                       {"minAmountCny": threshold, "pageSize": 100})
    calls.append({"tool": "ap.invoice.listBlocked",
                  "arguments": {"minAmountCny": threshold, "pageSize": 100}, "ok": True})

    items = page.get("items", [])
    info = page.get("pageInfo") or {}
    filtered = page.get("filteredByDimension") or {}
    dims = "、".join(filtered.get("dimensions") or []) or "无"

    lines = [f"按本租户大额风险口径：单张发票 ≥ {fmt_amount(threshold)} 元（来源：{source}；"
             f"解析层：{meta.get('sourceLayer', 'standard')}）。",
             f"当前权限范围内命中 {len(items)} 张大额阻断发票（数据权限过滤维度：{dims}）："]
    for it in items[:10]:
        lines.append(f"  - {it.get('invoiceNo')}：{fmt_amount(it.get('amountCny'))} 元"
                     f"（{it.get('supplier', '-')}，{it.get('org', '-')}）"
                     f" 原因：{'、'.join(it.get('blockedReasons') or [])}")
    if info.get("truncated"):
        lines.append("（结果被截断，仅显示前 10 条）")
    return {"tool_calls": calls, "result": page, "answer": "\n".join(lines)}


def done(state: GraphState) -> dict:
    return {}


def build():
    return build_graph(
        GraphState,
        nodes=[("classify", classify), ("diagnose", diagnose),
               ("large_risk", large_risk), ("done", done)],
        edges=[("START", "classify"), ("diagnose", "END"), ("large_risk", "END"),
               ("done", "END")],
        conditional={"classify": (route, ["diagnose", "large_risk", "done"])})
