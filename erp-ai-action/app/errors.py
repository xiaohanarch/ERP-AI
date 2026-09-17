"""统一错误信封：与 boapi-spec 错误结构对齐（error{code, category, message, retryable, ...}）。"""
from __future__ import annotations

from fastapi.responses import JSONResponse


def error_body(code: str, message: str, category: str, *,
               retryable: bool = False, retry_after_seconds: int | None = None,
               remediation: dict | str | None = None, field: str | None = None,
               trace_id: str | None = None) -> dict:
    err: dict = {"code": code, "category": category, "message": message, "retryable": retryable}
    if retry_after_seconds is not None:
        err["retry_after_seconds"] = retry_after_seconds
    if remediation is not None:
        err["remediation"] = remediation
    if field is not None:
        err["field"] = field
    if trace_id is not None:
        err["trace_id"] = trace_id
    return {"error": err}


def gw_json(status: int, code: str, message: str, category: str, **kw) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, category, **kw))


# 常用错误码快捷构造（网关策略类，与 bo-ap.yaml GW.* 对齐）
def agent_not_registered(agent_id: str) -> JSONResponse:
    return gw_json(401, "GW.AGENT_NOT_REGISTERED",
                   f"代理未注册：{agent_id}", "gateway_policy")


def agent_revoked(agent_id: str) -> JSONResponse:
    return gw_json(401, "GW.AGENT_REVOKED",
                   f"代理已吊销：{agent_id}（注册中心即时生效）", "gateway_policy")


def scope_exceeded(tool: str) -> JSONResponse:
    return gw_json(403, "GW.SCOPE_EXCEEDED",
                   f"越权调用：T2 scope 不包含工具 {tool}", "gateway_policy")


def tenant_mismatch(detail: str) -> JSONResponse:
    return gw_json(403, "GW.TENANT_MISMATCH", detail, "gateway_policy")


def scene_disabled(scene: str) -> JSONResponse:
    return gw_json(403, "GW.SCENE_DISABLED",
                   f"场景已降级停用：{scene}", "gateway_policy",
                   remediation={"action": "联系平台管理员恢复场景"})


def sod_conflict(groups: list[str]) -> JSONResponse:
    return gw_json(403, "GW.SOD_CONFLICT",
                   f"SoD 互斥冲突：同一代理不得同时持有 {groups}", "gateway_policy")


def approval_required(approval_id: str, message: str) -> JSONResponse:
    return gw_json(403, "GW.APPROVAL_REQUIRED", message, "gateway_policy",
                   retryable=True,
                   remediation={"action": "等待审批人批准后，携带一次性令牌（approvalToken）重发相同请求",
                                "approval_id": approval_id})


def approval_token_expired() -> JSONResponse:
    return gw_json(401, "GW.APPROVAL_TOKEN_EXPIRED",
                   "一次性审批令牌已过期或已使用", "gateway_policy", retryable=True)


def approval_params_mismatch() -> JSONResponse:
    return gw_json(409, "GW.APPROVAL_PARAMS_MISMATCH",
                   "审批参数与本次请求不一致（params_hash 校验失败）", "gateway_policy")


def unauthorized(message: str = "凭据缺失或无效") -> JSONResponse:
    return gw_json(401, "GW.UNAUTHORIZED", message, "gateway_policy")


def validation_error(message: str) -> JSONResponse:
    return gw_json(400, "AP.VALIDATION_ERROR", message, "validation_error")


def internal_error(message: str = "网关内部错误（演示环境，详见服务日志）") -> JSONResponse:
    return gw_json(500, "GW.INTERNAL_ERROR", message, "retryable_failure", retryable=True)
