"""图状态与回答组装共享工具（四场景共用一个 state schema）。"""
from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    """全场景共享状态（无 reducer，后写覆盖）。"""
    # 入口上下文
    message: str
    user: str
    tenant: str
    trace: str
    conversation_id: str
    model_mode: str                # 逐请求模型模式钉定（mock/replay/live；空=全局默认）
    delegate_from: str             # 委派方代理 id（被委派执行时携带；exchange 时 act 链增长）
    # 模型动作（动作契约：intent + invoiceNo/poNo + reply / taxCode + reason）
    intent: str
    invoice_no: str
    po_no: str                     # 采购域（proc.diag / xdom 委派）
    # 跨域协同（xdom.diag）
    ap_result: dict
    proc_result: dict
    proc_answer: str
    proc_error: str | None
    # 税码建议（写路径）
    suggestion: dict
    pending_args: dict
    pending_context: dict
    approval: dict
    approval_result: str          # pending | applied | rejected | failed
    ot: dict | None
    # 受限自主只读（ap.explore，第二档）
    last_call: dict                  # 当步单次调用（SSE 增量发射通道，避免累计清单重发）
    next_tool: str                   # 模型决定的下一步工具（None = 收尾）
    next_args: dict                 # 下一步参数
    history: list[dict]             # 已取得的工具结果（喂回模型做下一步决策）
    final_answer: str               # 模型给出的收尾结论（超步数时可能为空）
    # 工具可见性与结果
    tool_calls: list[dict]
    result: Any
    answer: str
    error: dict | None


def ctx_of(state: dict) -> dict:
    return {"user": state.get("user"), "tenant": state.get("tenant"),
            "trace": state.get("trace"), "model_mode": state.get("model_mode") or ""}


def fmt_amount(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------- 动作契约（模型 -> 图）
# mock 模型按场景脚本化输出同一契约；live 模型靠这段系统提示对齐 —— 图只认契约 JSON，
# 不感知模型来自哪一层（mock / 录制 / 真实供应商）。
CONTRACTS: dict[str, str] = {
    "ap.diag": (
        "你是应付（AP）域发票诊断助手的意图分类器。只输出一个 JSON 对象（不要 markdown 代码块、"
        "不要任何多余文字），按用户消息选择意图：\n"
        '1. 用户提到具体发票号（形如 INV-A-001）并想了解校验/阻断/差异原因 -> '
        '{"intent":"diagnose","invoiceNo":"<发票号>","reply":"好的，我对发票 <发票号> 执行校验并归因阻断原因。"}\n'
        '2. 用户想筛查大额/风险发票且未给具体发票号 -> '
        '{"intent":"large_risk","reply":"好的，我按当前租户的大额风险口径筛查发票。"}\n'
        '3. 信息不足 -> {"intent":"clarify","reply":"请提供发票号（如 INV-A-001），或描述要筛查的范围。"}'
    ),
    "ap.batch": (
        "你是应付（AP）域批量筛查助手的意图分类器。只输出一个 JSON 对象（不要 markdown 代码块、"
        "不要任何多余文字）：\n"
        '1. 用户描述筛查诉求（含大额/风险口径，或泛泛要求列阻断发票） -> '
        '{"intent":"batch_screen","reply":"好的，我来筛查当前权限范围内被阻断的发票，并统计主要原因。"}\n'
        '2. 信息不足 -> {"intent":"clarify","reply":"请描述筛查范围（如：全部阻断发票 / 大额风险发票）。"}'
    ),
    "ap.taxcode": (
        "你是应付（AP）域税码建议助手。只输出一个 JSON 对象（不要 markdown 代码块、不要任何多余文字）：\n"
        '1. 用户要求补全/调整税码并提供了发票号 -> '
        '{"intent":"suggest_tax_code","invoiceNo":"<发票号>","taxCode":"CN-VAT-13",'
        '"reason":"根据供应商所在地常用税码（规则 AP.TAX.CODE_SUGGESTED），建议适用 13% 增值税码。",'
        '"reply":"根据供应商所在地常用税码，建议将 <发票号> 的税码调整为 CN-VAT-13。是否提交申请？（提交后将进入审批流程）"}\n'
        "（用户未明确指定税码时一律建议 CN-VAT-13；用户明确给了税码则用用户的值）\n"
        '2. 没有发票号 -> {"intent":"clarify","reply":"请提供需要补全税码的发票号（如 INV-A-003）。"}'
    ),
    "proc.diag": (
        "你是采购域查询助手。只输出一个 JSON 对象（不要 markdown 代码块、不要任何多余文字）：\n"
        '1. 用户提到采购订单号（形如 PO-A-0001）或询问订单/收货情况 -> '
        '{"intent":"po_lookup","poNo":"<订单号>","reply":"好的，我查询该采购订单的详情与收货情况。"}\n'
        '2. 信息不足 -> {"intent":"clarify","reply":"请提供采购订单号（如 PO-A-0001）。"}'
    ),
    "xdom.diag": (
        "你是应付（AP）域跨域诊断助手的意图分类器。只输出一个 JSON 对象（不要 markdown 代码块、"
        "不要任何多余文字）：\n"
        '1. 用户提到具体发票号（形如 INV-A-001）并想了解阻断原因（含采购/收货侧情况） -> '
        '{"intent":"diagnose_cross","invoiceNo":"<发票号>",'
        '"reply":"好的，我做跨域归因：先 AP 侧诊断，再委派采购域取证。"}\n'
        '2. 信息不足 -> {"intent":"clarify","reply":"请提供发票号（如 INV-A-001）。"}'
    ),
    "ap.explore": (
        '你是应付（AP）域的只读探索助手（第二档·受限自主：安全由平台约束保证，不靠你自觉）。'
        '根据问题与已取得的工具结果，决定下一步动作，只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字）：'
        '继续取证 -> {"action":"call","tool":"<工具名>","arguments":{...}}（工具只能从对话中列出的白名单选择，全部只读）；'
        '证据足够 -> {"action":"final","answer":"<结论>"}。'
        '结论必须引用已取得的发现（规则码/数字），不发明未取得的事实；通常 2~3 步内收尾。'
    ),
    "ap.event": (
        '你是应付发票的事件诊断摘要器，把无头诊断的校验结果讲成人话。'
        '根据用户消息中的校验发现，输出一到三句归因摘要：说清最重要的阻断原因与建议的下一步。'
        '只依据给出的发现，不发明未提及的事实。'
        '只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字）：'
        '{"intent":"event_summary","summary":"<归因摘要>"}'
    ),
}


def contract_messages(scene: str, message: str) -> list[dict]:
    """带动作契约系统提示的消息序列（live 模型对齐 mock 契约；mock 不受影响）。"""
    system = CONTRACTS.get(scene)
    msgs = [{"role": "system", "content": system}] if system else []
    msgs.append({"role": "user", "content": message})
    return msgs
