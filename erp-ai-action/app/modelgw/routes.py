"""模型网关路由。

- POST /v1/chat/completions   OpenAI 兼容出口（hub 调用；IN 令牌或后端客户凭据）
- GET  /gw/modelgw/status     模式/录制/版本戳（admin/internal；自检用）
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import gw_json, internal_error, unauthorized
from app.modelgw import service
from app.security import is_admin, verify_backend_client, verify_token

router = APIRouter()


def _client_ctx(request: Request) -> dict | None:
    """鉴权：Bearer IN（网关铸造）或后端客户凭据头。返回调用上下文。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        claims = verify_token(auth[7:])
        if claims and claims.get("azp") == "erp-ai-action" and claims.get("aud") == "erp-ai-hub":
            sub = claims["sub"]
            return {"user": sub[2:] if sub.startswith("u-") else sub,
                    "tenant": claims.get("tid"), "agent": None,
                    "trace": request.headers.get("X-GW-Trace")}
    client_id = request.headers.get("X-Client-Id", "")
    client_secret = request.headers.get("X-Client-Secret", "")
    if client_id and client_secret and verify_backend_client(client_id, client_secret):
        return {"user": request.headers.get("X-GW-User") or client_id,
                "tenant": request.headers.get("X-GW-Tenant"),
                "agent": request.headers.get("X-GW-Agent"),
                "trace": request.headers.get("X-GW-Trace")}
    return None


@router.post("/v1/chat/completions")
def chat_completions(request: Request, payload: dict):
    if payload.get("stream"):
        return gw_json(400, "GW.STREAM_UNSUPPORTED",
                       "模型网关仅支持非流式调用（SSE 由 hub 切片）", "validation_error")
    ctx = _client_ctx(request)
    if ctx is None:
        return unauthorized("需要 IN 令牌或后端客户凭据（X-Client-Id/X-Client-Secret）")
    mode_override = request.headers.get("X-Model-Mode", "")
    if mode_override and mode_override not in service.VALID_MODES:
        return gw_json(400, "GW.INVALID_MODEL_MODE",
                       f"X-Model-Mode 必须是 {service.VALID_MODES} 之一，收到 {mode_override!r}",
                       "validation_error", retryable=False)
    try:
        response, source = service.chat_completion(payload, ctx,
                                                   mode_override=mode_override or None)
    except service.ModelGwError as e:
        return gw_json(e.status, e.code, e.message,
                       "retryable_failure" if e.retryable else "gateway_policy",
                       retryable=e.retryable)
    except Exception as e:  # noqa: BLE001
        print(f"[modelgw] 调用异常：{e}", flush=True)
        return internal_error()
    return JSONResponse(content=response, headers={"X-GW-Source": source})


@router.get("/gw/modelgw/status")
def modelgw_status(request: Request):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    return service.status()
