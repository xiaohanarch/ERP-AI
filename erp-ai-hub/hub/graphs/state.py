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
    # 模型动作（动作契约：intent + invoiceNo + reply / taxCode + reason）
    intent: str
    invoice_no: str
    # 税码建议（写路径）
    suggestion: dict
    pending_args: dict
    pending_context: dict
    approval: dict
    approval_result: str          # pending | applied | rejected | failed
    ot: dict | None
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
}


def contract_messages(scene: str, message: str) -> list[dict]:
    """带动作契约系统提示的消息序列（live 模型对齐 mock 契约；mock 不受影响）。"""
    system = CONTRACTS.get(scene)
    msgs = [{"role": "system", "content": system}] if system else []
    msgs.append({"role": "user", "content": message})
    return msgs
