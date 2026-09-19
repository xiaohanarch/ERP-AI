"""租户消息订阅：SaaS 扩展通道（Message 半边）。

标品层产生领域事件（存量域 outbox，hub 事件线程消费），租户层通过订阅
（topic + webhook + 签名密钥）把事件接进自己的系统——平台不开放核心改造，
租户不动标品代码。投递按（租户 × topic）严格隔离：T-EAST 的事件绝不投给
T-UNI 的订阅；每次投递携带 HMAC-SHA256 签名（租户侧验签防伪造）并留审计。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import httpx

from app import audit, db


class SubscriptionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def register(tenant_id: str, topic: str, endpoint_url: str, secret: str) -> dict:
    tenant_id, topic = tenant_id.strip(), topic.strip()
    endpoint_url, secret = endpoint_url.strip(), secret.strip()
    if not tenant_id or not topic or not endpoint_url or not secret:
        raise SubscriptionError("AP.VALIDATION_ERROR",
                                "tenantId/topic/endpointUrl/secret 必填")
    if not endpoint_url.startswith(("http://", "https://")):
        raise SubscriptionError("AP.VALIDATION_ERROR", "endpointUrl 必须是 http(s) 地址")
    existing = db.query(
        "SELECT subscription_id FROM subscriptions WHERE tenant_id=%s AND topic=%s "
        "AND endpoint_url=%s AND status='ACTIVE'", (tenant_id, topic, endpoint_url), one=True)
    if existing:
        raise SubscriptionError("AP.VALIDATION_ERROR",
                                f"该（租户 × topic × 端点）已有活跃订阅：{existing['subscription_id']}")
    subscription_id = f"sub-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO subscriptions (subscription_id, tenant_id, topic, endpoint_url, secret) "
        "VALUES (%s, %s, %s, %s, %s)",
        (subscription_id, tenant_id, topic, endpoint_url, secret))
    audit.record(action="subscription.register", outcome="SUCCESS", tenant_id=tenant_id,
                 detail={"subscriptionId": subscription_id, "topic": topic,
                         "endpointUrl": endpoint_url})
    return {"subscriptionId": subscription_id, "tenantId": tenant_id, "topic": topic,
            "endpointUrl": endpoint_url, "status": "ACTIVE"}


def list_subscriptions(tenant_id: str | None = None) -> list[dict]:
    if tenant_id:
        rows = db.query("SELECT * FROM subscriptions WHERE tenant_id=%s ORDER BY created_at",
                        (tenant_id,))
    else:
        rows = db.query("SELECT * FROM subscriptions ORDER BY created_at")
    return [{
        "subscriptionId": r["subscription_id"], "tenantId": r["tenant_id"],
        "topic": r["topic"], "endpointUrl": r["endpoint_url"], "status": r["status"],
        "revokedAt": r["revoked_at"].isoformat() if r["revoked_at"] else None,
        "createdAt": r["created_at"].isoformat(),
    } for r in rows]


def revoke(subscription_id: str) -> dict:
    row = db.query("SELECT * FROM subscriptions WHERE subscription_id=%s",
                   (subscription_id,), one=True)
    if row is None:
        raise SubscriptionError("GW.SUBSCRIPTION_NOT_FOUND", f"订阅不存在：{subscription_id}")
    db.execute("UPDATE subscriptions SET status='REVOKED', revoked_at=now() "
               "WHERE subscription_id=%s", (subscription_id,))
    audit.record(action="subscription.revoke", outcome="SUCCESS",
                 tenant_id=row["tenant_id"],
                 detail={"subscriptionId": subscription_id, "topic": row["topic"]})
    return {"subscriptionId": subscription_id, "status": "REVOKED"}


def dispatch(event: dict) -> dict:
    """领域事件扇出：按（租户 × topic）匹配活跃订阅，逐个投递并留痕。

    event 即 outbox 载荷（eventType/tenantId/invoiceNo/...）；无订阅时为
    无操作（返回 matched=0）。每次投递独立审计（event.dispatch），失败
    记 ERROR 但不阻断其他订阅。
    """
    tenant_id = str(event.get("tenantId") or "")
    event_type = str(event.get("eventType") or "")
    if not tenant_id or not event_type:
        return {"matched": 0, "delivered": [], "error": "事件缺少 tenantId/eventType"}
    rows = db.query(
        "SELECT * FROM subscriptions WHERE tenant_id=%s AND topic=%s AND status='ACTIVE'",
        (tenant_id, event_type))
    delivered = []
    for r in rows:
        delivery_id = f"dlv-{uuid.uuid4().hex[:12]}"
        body = dict(event, deliveryId=delivery_id, topic=event_type)
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        signature = hmac.new(r["secret"].encode("utf-8"), raw, hashlib.sha256).hexdigest()
        status, ok, err = None, False, None
        try:
            resp = httpx.post(r["endpoint_url"], content=raw, timeout=10, headers={
                "Content-Type": "application/json",
                "X-ERP-Delivery-Id": delivery_id,
                "X-ERP-Event-Type": event_type,
                "X-ERP-Signature": f"sha256={signature}",
            })
            status = resp.status_code
            ok = 200 <= resp.status_code < 300
        except httpx.HTTPError as e:  # noqa: BLE001 —— 单个订阅投递失败不阻断其余
            err = str(e)[:120]
        audit.record(action="event.dispatch", outcome="SUCCESS" if ok else "ERROR",
                     tenant_id=tenant_id, http_status=status,
                     error_code=None if ok else "GW.WEBHOOK_DELIVERY_FAILED",
                     detail={"subscriptionId": r["subscription_id"], "deliveryId": delivery_id,
                             "topic": event_type, "invoiceNo": event.get("invoiceNo"),
                             "redelivered": bool(event.get("redelivered"))})
        delivered.append({"subscriptionId": r["subscription_id"], "deliveryId": delivery_id,
                          "httpStatus": status, "ok": ok, "error": err})
    return {"matched": len(rows), "delivered": delivered,
            "tenantId": tenant_id, "topic": event_type}
