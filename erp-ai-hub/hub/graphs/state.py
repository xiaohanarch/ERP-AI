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
    # 模型动作（mock 契约：intent + invoiceNo + reply / taxCode + reason）
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
            "trace": state.get("trace")}


def fmt_amount(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)
