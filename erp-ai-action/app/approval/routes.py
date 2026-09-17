"""审批路由（WorkBuddy Approvals 页消费；三要素展示）。

- GET  /gw/approvals                 本租户审批任务列表（T1）
- GET  /gw/approvals/{id}            详情（含三要素 + snapshot）
- POST /gw/approvals/{id}/decision   批准/拒绝（校验 ap.approval.decide；批准铸 OT）
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import audit
from app.approval import service
from app.errors import gw_json, unauthorized, validation_error
from app.security import require_t1

router = APIRouter()


@router.get("/gw/approvals")
def list_approvals(request: Request, status: str | None = None):
    claims = require_t1(request)
    tenant = claims.get("tid")
    items = service.list_for_tenant(tenant, status)
    return {"count": len(items), "items": items}


@router.get("/gw/approvals/{approval_id}")
def approval_detail(approval_id: str, request: Request):
    claims = require_t1(request)
    task = service.get(approval_id)
    if task is None:
        return gw_json(404, "GW.APPROVAL_NOT_FOUND", f"审批任务不存在：{approval_id}", "gateway_policy")
    if task["tenantId"] != claims.get("tid"):
        return gw_json(403, "GW.TENANT_MISMATCH", "跨租户访问审批任务被拒绝", "gateway_policy")
    return task


@router.post("/gw/approvals/{approval_id}/decision")
def decide(approval_id: str, request: Request, body: dict):
    claims = require_t1(request)
    username = claims["sub"][2:] if claims["sub"].startswith("u-") else claims["sub"]
    tenant = claims.get("tid")
    action = str(body.get("action", ""))
    if action not in ("approve", "reject"):
        return validation_error("action 必须为 approve 或 reject")
    try:
        result = service.decide(approval_id, action, approver_username=username,
                                approver_tenant=tenant, comment=body.get("comment"))
    except service.ApprovalError as e:
        audit.record(tenant_id=tenant, user_id=username, action="approval.decide",
                     outcome="DENIED", error_code=e.code, approval_id=approval_id,
                     detail={"action": action})
        return gw_json(e.status, e.code, e.message, e.category)
    audit.record(tenant_id=tenant, user_id=username, action="approval.decide",
                 outcome="SUCCESS", approval_id=approval_id,
                 approver=result.get("approver"),
                 detail={"action": action, "newStatus": result["status"]})
    return result
