"""平台杂项路由：场景降级开关 / 通知 / 版本戳 / 健康。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import notifications
from app.errors import unauthorized, validation_error
from app.mcp import scenes as scenes_mod
from app.mcp.tool_registry import tool_registry
from app.security import is_admin, require_t1

router = APIRouter()


# ---------------------------------------------------------------- 场景
@router.get("/gw/scenes")
def list_scenes(request: Request):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    return {"scenes": scenes_mod.all_scenes()}


@router.post("/gw/scenes/{scene}/toggle")
def toggle_scene(scene: str, request: Request, body: dict):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return validation_error("enabled 必须为布尔值")
    if not scenes_mod.set_enabled(scene, enabled):
        return validation_error(f"未知场景：{scene}")
    return {"scene": scene, "enabled": enabled}


# ---------------------------------------------------------------- 通知
@router.get("/gw/notifications")
def list_notifications(request: Request, unread_only: bool = False):
    claims = require_t1(request)
    username = claims["sub"][2:] if claims["sub"].startswith("u-") else claims["sub"]
    items = notifications.list_for(username, unread_only)
    return {"count": len(items), "items": items}


@router.post("/gw/notifications/{notification_id}/read")
def read_notification(notification_id: int, request: Request):
    claims = require_t1(request)
    username = claims["sub"][2:] if claims["sub"].startswith("u-") else claims["sub"]
    if not notifications.mark_read(username, notification_id):
        return validation_error("通知不存在或不属于当前用户")
    return {"ok": True}


@router.post("/internal/notifications")
def internal_push_notification(request: Request, body: dict):
    """内部通知入口（hub 事件订阅无头诊断后推送；X-Internal-Secret 鉴权）。"""
    from app.security import is_internal
    if not is_internal(request):
        return unauthorized("需要内部密钥（X-Internal-Secret）")
    tenant_id = body.get("tenantId")
    username = str(body.get("username") or "").strip()
    kind = str(body.get("kind") or "event_diag").strip()
    if not username:
        return validation_error("username 必填")
    if kind == "event_diag":
        notifications.push_event_diag(tenant_id, username,
                                      str(body.get("invoiceNo") or ""),
                                      str(body.get("summary") or ""))
    else:
        notifications.push(tenant_id, username, kind,
                           str(body.get("title") or "通知"),
                           str(body.get("body") or ""))
    return {"ok": True}


# ---------------------------------------------------------------- 版本与健康
@router.get("/gw/versions")
def versions():
    """版本四件套（评测证据锚点：spec/seed/ruleset + 语义版本）。"""
    from app.modelgw.service import semantics_version
    v = tool_registry.versions()
    v["semanticsVersion"] = semantics_version()
    return v


@router.get("/healthz")
def healthz():
    from app import db
    try:
        db.query("SELECT 1 AS ok", one=True)
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok,
            "specVersion": tool_registry.spec_version}
