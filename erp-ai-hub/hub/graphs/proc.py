"""proc.diag 场景图：采购域查询（订单详情 + 收货取证，读侧）。

两种使用方式：
  - 独立场景：用户直接询问采购订单/收货情况；
  - 被委派执行：xdom.diag 的 delegate 节点以内联子图运行本图，
    state.delegate_from 携带委派方代理 -> exchange 时 act 委托链增长，
    工具调用以本代理（proc-copilot）自己的 T2 执行（最小权限）。
"""
from __future__ import annotations

from hub import gw
from hub.graphs.agents import agent_for
from hub.graphs.state import GraphState, contract_messages, ctx_of, fmt_amount
from hub.sdk import build_graph

AGENT = "proc-copilot"
SCENE = "proc.diag"

_STATUS_ZH = {"POSTED": "已过账", "OPEN": "开放", "CLOSED": "已关闭", "DRAFT": "草稿"}


def classify(state: GraphState) -> dict:
    action = gw.ask_model(SCENE, contract_messages(SCENE, state["message"]), ctx_of(state))
    return {"intent": action.get("intent", "clarify"),
            "po_no": action.get("poNo") or state.get("po_no"),
            "tool_calls": [], "error": None,
            "answer": action.get("reply") if action.get("intent") == "clarify" else None}


def _route(state: GraphState) -> str:
    return "lookup" if state.get("intent") == "po_lookup" and state.get("po_no") else "done"


def lookup(state: GraphState) -> dict:
    """订单详情 + 收货取证（被委派时 delegated_by 传入 exchange，act 链增长）。"""
    user, tenant = state["user"], state["tenant"]
    po_no = str(state.get("po_no") or "")
    delegated_from = state.get("delegate_from") or None

    tools = ["proc.po.getDetail", "proc.gr.listForPo"]
    t2 = gw.exchange(agent_for(AGENT, tenant), SCENE, tools, user, tenant,
                     delegated_by=delegated_from)
    calls = [{"tool": "proc.po.getDetail", "arguments": {"poNo": po_no}, "ok": True}]
    po = gw.mcp_call(t2, "proc.po.getDetail", {"poNo": po_no})
    calls.append({"tool": "proc.gr.listForPo", "arguments": {"poNo": po_no}, "ok": True})
    grs = gw.mcp_call(t2, "proc.gr.listForPo", {"poNo": po_no})

    status = str(po.get("status") or "")
    lines = [f"采购订单 {po.get('poNo')}：状态 {status}（{_STATUS_ZH.get(status, status)}），"
             f"供应商 {po.get('supplier') or '-'}，下单日期 {po.get('orderDate') or '-'}，"
             f"订单总额 {fmt_amount(po.get('orderTotalCny'))} 元。"]
    for ln in po.get("lines", []):
        lines.append(f"  - {ln.get('item')}：订购 {fmt_amount(ln.get('orderQty'))}"
                     f" × {fmt_amount(ln.get('unitPrice'))} 元，已收 {fmt_amount(ln.get('receivedQty'))}")
    lines.append(f"收货情况：共 {grs.get('receiptCount')} 张收货单，"
                 f"累计收货 {fmt_amount(grs.get('totalReceivedQty'))}。")
    for r in grs.get("receipts", [])[:5]:
        items = "、".join(f"{l.get('item')}×{fmt_amount(l.get('qty'))}" for l in r.get("lines", []))
        lines.append(f"  - {r.get('grNo')}（{r.get('receiptDate') or '-'}）：{items}")
    complete = po.get("receivedComplete")
    if complete is True:
        lines.append("结论：订单已收齐（已收量 = 订购量）。")
    elif complete is False:
        lines.append("结论：订单存在未收齐行（已收量 < 订购量）。")

    return {"tool_calls": calls, "result": {"po": po, "receipts": grs},
            "answer": "\n".join(lines)}


def done(state: GraphState) -> dict:
    return {}


def build():
    return build_graph(
        GraphState,
        nodes=[("classify", classify), ("lookup", lookup), ("done", done)],
        edges=[("START", "classify"), ("lookup", "END"), ("done", "END")],
        conditional={"classify": (_route, ["lookup", "done"])})
