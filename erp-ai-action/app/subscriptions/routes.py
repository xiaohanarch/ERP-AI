"""订阅路由：注册/清册/吊销（admin / 内部密钥）+ 事件分发（内部，hub 调用）。

  POST /gw/subscriptions                   注册（租户 × topic × webhook × 密钥）
  GET  /gw/subscriptions?tenant_id=        清册（管理侧/自检取证）
  POST /gw/subscriptions/{id}/revoke       吊销（对后续投递即时生效）
  POST /internal/events/dispatch           事件扇出（hub 事件线程调用；X-Internal-Secret）
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import audit
from app.errors import gw_json, unauthorized, validation_error
from app.subscriptions import service
from app.security import is_admin, is_internal

router = APIRouter()


@router.post("/gw/subscriptions")
def register_subscription(request: Request, body: dict):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    try:
        result = service.register(
            str(body.get("tenantId", "")), str(body.get("topic", "")),
            str(body.get("endpointUrl", "")), str(body.get("secret", "")))
    except service.SubscriptionError as e:
        return validation_error(e.message)
    return result


@router.get("/gw/subscriptions")
def list_subscription(request: Request, tenant_id: str | None = None):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    items = service.list_subscriptions(tenant_id)
    audit.record(action="subscription.roster.view", outcome="SUCCESS", tenant_id=tenant_id,
                 detail={"count": len(items)})
    return {"count": len(items), "subscriptions": items}


@router.post("/gw/subscriptions/{subscription_id}/revoke")
def revoke_subscription(subscription_id: str, request: Request):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    try:
        return service.revoke(subscription_id)
    except service.SubscriptionError as e:
        return gw_json(404, e.code, e.message, "gateway_policy")


@router.post("/internal/events/dispatch")
def dispatch_event(request: Request, body: dict):
    """领域事件扇出到租户订阅（hub 事件线程调用；事件载荷内含租户与 topic）。"""
    if not is_internal(request):
        return unauthorized("需要内部密钥（X-Internal-Secret）")
    event = body.get("event")
    if not isinstance(event, dict):
        return validation_error("event 必填（outbox 载荷对象）")
    return service.dispatch(event)
