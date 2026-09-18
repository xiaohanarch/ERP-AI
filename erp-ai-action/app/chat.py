"""聊天入口：/gw/chat/stream（SSE）。T1 -> IN -> hub，逐事件透传。

事件协议（hub 产生，网关透传，页面消费）：
  {"type":"meta",...}  会话元信息（agent/scene/trace_id）
  {"type":"token",...} 回复切片
  {"type":"tool",...}  工具调用可见性
  {"type":"approval_required",...} 写路径挂起（interrupt）
  {"type":"error",...} / {"type":"done",...}
"""
from __future__ import annotations

import json
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import audit, otel_setup
from app.auth import token_service as ts
from app.config import settings
from app.mcp import scenes as scenes_mod
from app.security import require_t1

router = APIRouter()

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8"}


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/gw/chat/stream")
def chat_stream(request: Request, body: dict):
    claims = require_t1(request)
    username = claims["sub"][2:] if claims["sub"].startswith("u-") else claims["sub"]
    tenant = claims.get("tid")
    message = str(body.get("message", "")).strip()
    scene = str(body.get("scene") or "ap.diag")
    conversation_id = str(body.get("conversationId") or f"c-{uuid.uuid4().hex[:12]}")
    # 逐请求模型模式钉定（mock|replay|live）：评测/六幕脚本锁确定性，交互面走全局默认
    model_mode = request.headers.get("X-Model-Mode", "")
    if model_mode and model_mode not in ("mock", "replay", "live"):
        def err_mode():
            yield _sse_event({"type": "error", "code": "GW.INVALID_MODEL_MODE",
                              "message": f"X-Model-Mode 必须是 mock/replay/live，收到 {model_mode!r}"})
            yield _sse_event({"type": "done"})
        return StreamingResponse(err_mode(), headers=_SSE_HEADERS)

    trace_id = uuid.uuid4().hex
    audit.record(tenant_id=tenant, user_id=username, azp=claims.get("azp"),
                 action="chat.submit", outcome="SUCCESS", scene=scene,
                 trace_id=trace_id, detail={"conversationId": conversation_id,
                                             "messageLength": len(message)})

    if not message:
        def err_empty():
            yield _sse_event({"type": "error", "code": "AP.VALIDATION_ERROR",
                              "message": "消息不能为空"})
            yield _sse_event({"type": "done"})
        return StreamingResponse(err_empty(), headers=_SSE_HEADERS)

    if not scenes_mod.is_enabled(scene):
        def err_scene():
            yield _sse_event({"type": "error", "code": "GW.SCENE_DISABLED",
                              "message": f"场景 {scene} 已降级停用，请联系平台管理员"})
            yield _sse_event({"type": "done"})
        audit.record(tenant_id=tenant, user_id=username, action="chat.error",
                     outcome="DENIED", scene=scene, trace_id=trace_id,
                     error_code="GW.SCENE_DISABLED")
        return StreamingResponse(err_scene(), headers=_SSE_HEADERS)

    in_token = ts.mint_in(username, tenant, display_name=claims.get("name"), org=claims.get("org"))

    with otel_setup.span("invoke_agent", {
        "enduser.id": username,
        "scene.code": scene, "scene.tenant": tenant,
        "trace_id": trace_id,
        "bo.action": "chat",
    }):
        return StreamingResponse(_relay(message, scene, conversation_id, username, tenant,
                                        in_token, trace_id, model_mode),
                                 headers=_SSE_HEADERS)


def _relay(message: str, scene: str, conversation_id: str, username: str, tenant: str | None,
           in_token: str, trace_id: str, model_mode: str = ""):
    """hub SSE 逐事件透传；异常时以 error + done 收尾（协议永不悬空）。"""
    payload = {"message": message, "scene": scene, "conversationId": conversation_id,
               "user": username, "tenant": tenant, "traceId": trace_id}
    headers = {"Authorization": f"Bearer {in_token}", "Content-Type": "application/json"}
    if model_mode:
        headers["X-Model-Mode"] = model_mode
    try:
        with httpx.stream("POST", f"{settings.hub_base}/chat/stream", json=payload,
                          headers=headers, timeout=httpx.Timeout(30, read=180)) as resp:
            if resp.status_code != 200:
                yield _sse_event({"type": "error", "code": "GW.HUB_UNAVAILABLE",
                                  "message": f"hub 返回 {resp.status_code}"})
                yield _sse_event({"type": "done"})
                _audit_done(username, tenant, scene, trace_id, "ERROR", f"hub_{resp.status_code}")
                return
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    yield line + "\n\n"
                elif line.startswith("event:"):
                    yield line + "\n"
                else:
                    yield line + "\n\n"
            yield _sse_event({"type": "done"})
            _audit_done(username, tenant, scene, trace_id, "SUCCESS", None)
    except httpx.HTTPError as e:
        yield _sse_event({"type": "error", "code": "GW.HUB_UNAVAILABLE",
                          "message": "hub 服务不可达（演示环境，请检查 hub 容器）"})
        yield _sse_event({"type": "done"})
        _audit_done(username, tenant, scene, trace_id, "ERROR", str(e)[:120])


def _audit_done(username, tenant, scene, trace_id, outcome, error):
    audit.record(tenant_id=tenant, user_id=username, action="chat.done", outcome=outcome,
                 scene=scene, trace_id=trace_id,
                 error_code="GW.HUB_UNAVAILABLE" if outcome == "ERROR" else None,
                 detail={"error": error} if error else None)
