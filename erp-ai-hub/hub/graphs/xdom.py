"""xdom.diag 场景图：跨域根因诊断（AP 归因 -> 委派采购域取证 -> 综合结论）。

多领域 Agent 协同（架构判断 6）的标的：AP 域只能看到「发票 vs 收货」的差异
（如 INV-A-001 开票 120 vs 收货 100），短交还是超开要结合采购域订单量定位
（PO-A-0001 订单 100 = 已收 100，故为供应商超开 20 件）。

委派机制（治理在网关，不在模型）：
  - ap-copilot 在注册表协作清单（agents.delegates_to）内声明 proc-copilot；
  - 网关 exchange 第七道校验：委派方在册/在期/同租户 + 目标在清单内，
    否则 403 GW.DELEGATION_NOT_ALLOWED；
  - 子代理以自己的 T2 执行（场景∩清单，最小权限），act 委托链增长为
    [proc-copilot -> ap-copilot -> erp-ai-hub]，经 T3 贯穿至存量域审计。
"""
from __future__ import annotations

from hub import gw
from hub.graphs import proc
from hub.graphs.agents import agent_for
from hub.graphs.state import GraphState, contract_messages, ctx_of, fmt_amount
from hub.sdk import build_graph, run_graph

AGENT = "ap-copilot"
SCENE = "xdom.diag"


def classify(state: GraphState) -> dict:
    action = gw.ask_model(SCENE, contract_messages(SCENE, state["message"]), ctx_of(state))
    return {"intent": action.get("intent", "clarify"),
            "invoice_no": action.get("invoiceNo") or state.get("invoice_no"),
            "tool_calls": [], "error": None,
            "answer": action.get("reply") if action.get("intent") == "clarify" else None}


def _route(state: GraphState) -> str:
    return "diagnose" if state.get("intent") == "diagnose_cross" and state.get("invoice_no") else "done"


def diagnose(state: GraphState) -> dict:
    """AP 侧归因：校验 + 匹配明细，提取 poNo 供跨域委派。"""
    user, tenant = state["user"], state["tenant"]
    inv = str(state.get("invoice_no") or "")
    tools = ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail"]
    t2 = gw.exchange(agent_for(AGENT, tenant), SCENE, tools, user, tenant)
    calls = [{"tool": "ap.invoice.checkValidation", "arguments": {"invoiceNo": inv}, "ok": True}]
    chk = gw.mcp_call(t2, "ap.invoice.checkValidation", {"invoiceNo": inv})
    calls.append({"tool": "ap.invoice.getMatchDetail", "arguments": {"invoiceNo": inv}, "ok": True})
    detail = gw.mcp_call(t2, "ap.invoice.getMatchDetail", {"invoiceNo": inv})

    findings: set[str] = set()
    for line in detail.get("lines", []):
        findings.update(line.get("findings") or [])
    qty_lines = [l for l in detail.get("lines", [])
                 if "AP.MATCH.QTY_MISMATCH" in (l.get("findings") or [])]
    return {"tool_calls": calls, "invoice_no": inv,
            "ap_result": {"check": chk, "detail": detail,
                          "findings": sorted(findings), "qty_lines": qty_lines},
            "po_no": detail.get("poNo") or "", "gr_no": detail.get("grNo") or ""}


def delegate(state: GraphState) -> dict:
    """委派采购域：proc-copilot 以自己的 T2 执行（act 链增长）；失败降级为 AP 侧结论。"""
    po_no = state.get("po_no") or ""
    if not po_no:
        return {"proc_result": None, "proc_answer": "", "proc_error": "发票未关联采购订单，无采购侧可查"}
    child_state = {
        "message": f"跨域委派（来自 {AGENT}）：查询采购订单 {po_no} 的详情与收货情况",
        "po_no": po_no, "user": state["user"], "tenant": state["tenant"],
        "trace": state.get("trace") or "",
        "conversation_id": f"{state.get('conversation_id') or 'xdom'}-proc",
        "delegate_from": AGENT, "model_mode": state.get("model_mode") or "",
    }
    try:
        values, _ = run_graph(proc.build(), child_state, child_state["conversation_id"])
        child_calls = values.get("tool_calls") or []
        return {"proc_result": values.get("result"), "proc_answer": values.get("answer", ""),
                "proc_error": None,
                # 子代理的工具调用并入父会话 SSE 流（节点增量语义：仅返回子代理的调用，
                # 父侧调用已由 diagnose 节点单独产出，避免重复事件）
                "tool_calls": child_calls}
    except Exception as e:  # noqa: BLE001 —— 委派失败不阻断 AP 侧结论
        return {"proc_result": None, "proc_answer": "",
                "proc_error": f"采购域委派失败：{e}"}


def synthesize(state: GraphState) -> dict:
    """综合归因：AP 差异 + 采购域上下文 -> 根因定位（超开/短交）与处置建议。"""
    ap = state.get("ap_result") or {}
    inv = state.get("invoice_no") or ""
    qty_lines = ap.get("qty_lines") or []
    lines = [f"【AP 域诊断】发票 {inv}：{'、'.join(ap.get("findings") or []) or '无异常'}。"]
    for l in qty_lines:
        diff = _diff(l.get("invoiceQty"), l.get("grQty"))
        lines.append(f"  数量差异：发票 {fmt_amount(l.get('invoiceQty'))}"
                     f" vs 收货 {fmt_amount(l.get('grQty'))}（{l.get('item')}，差异 {fmt_amount(diff)}）。")

    proc_answer = state.get("proc_answer") or ""
    if not proc_answer:
        lines.append(f"【采购域取证】未获得：{state.get('proc_error') or '无'}")
        lines.append("【综合结论】仅 AP 侧归因，请人工核对采购订单与收货单后定位根因。")
        return {"answer": "\n".join(lines)}

    lines.append("【采购域取证（委派 proc-copilot，act 链已增长）】")
    lines.append(proc_answer)

    po = (state.get("proc_result") or {}).get("po") or {}
    received_complete = po.get("receivedComplete")
    overbilled = None
    for l in qty_lines:
        po_qty, gr_qty, inv_qty = (_num(l.get("poQty")), _num(l.get("grQty")), _num(l.get("invoiceQty")))
        # 订单量 = 已收量 < 开票量 且整单已收齐 -> 供应商超开
        if received_complete and po_qty is not None and gr_qty is not None and inv_qty is not None \
                and gr_qty <= po_qty < inv_qty:
            overbilled = inv_qty - gr_qty
            break
    if overbilled is not None:
        lines.append(f"【综合结论】根因 = 供应商超开：订单量与收货量一致（整单已收齐），"
                     f"开票量高出 {fmt_amount(overbilled)}。")
        lines.append("处置建议：① 联系供应商对超出部分红字冲销或按实收数量重开发票；"
                     "② 发票维持阻断，不建议在此期间做税码补全；"
                     "③ 如确需超量采购，应先补采购订单、再收货开票。")
    elif received_complete is False:
        lines.append("【综合结论】根因 = 收货不完整：存在未收齐行，请先补收货或协商关闭订单，再处理发票。")
    else:
        lines.append("【综合结论】请对照 订单量/收货量/开票量 三方核对差异。")
    return {"answer": "\n".join(lines)}


def done(state: GraphState) -> dict:
    return {}


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _diff(a, b) -> float:
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return 0.0
    return x - y


def build():
    return build_graph(
        GraphState,
        nodes=[("classify", classify), ("diagnose", diagnose),
               ("delegate", delegate), ("synthesize", synthesize), ("done", done)],
        edges=[("START", "classify"), ("diagnose", "delegate"),
               ("delegate", "synthesize"), ("synthesize", "END"), ("done", "END")],
        conditional={"classify": (_route, ["diagnose", "done"])})
