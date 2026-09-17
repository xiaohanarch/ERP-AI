"""审批工作流：approval_task（三要素 + snapshot 留痕）+ 一次性令牌 OT。

状态机：PENDING -> APPROVED -> CONSUMED（OT 用掉）
                  -> REJECTED
        PENDING -> EXPIRED（超时，惰性判定）
"""
from __future__ import annotations

import json
import time
import uuid

import httpx

from app import db, notifications
from app.auth import token_service as ts
from app.config import settings
from app.security import new_id, params_hash as compute_hash


class ApprovalError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, category: str = "gateway_policy"):
        self.code = code
        self.message = message
        self.status = status
        self.category = category
        super().__init__(message)


def approvers_of(tenant_id: str) -> list[str]:
    return list(settings.approvers.get(tenant_id, []))


def create_task(*, tool: str, arguments: dict, tenant_id: str, requested_by: str,
                agent_id: str | None, scene: str | None, context: dict,
                trace_id: str | None = None) -> dict:
    """创建 PENDING 审批任务并通知审批人。三要素：rationale（做什么/依据）+ impact（影响范围）+ snapshot。"""
    approval_id = new_id("apr")
    p_hash = compute_hash(arguments)
    db.execute(
        "INSERT INTO approval_task (approval_id, tenant_id, scene, agent_id, tool, params, params_hash, "
        "requested_by, idempotency_key, rationale, impact, snapshot, status, trace_id, expires_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s, now() + interval '%s seconds')",
        (approval_id, tenant_id, scene, agent_id, tool,
         json.dumps(arguments, ensure_ascii=False), p_hash, requested_by,
         context.get("idempotencyKey"), context.get("rationale"), context.get("impact"),
         json.dumps(context.get("snapshot"), ensure_ascii=False),
         trace_id, settings.approval_pending_ttl_seconds))

    summary = (context.get("rationale") or f"{tool} 参数：{json.dumps(arguments, ensure_ascii=False)}")
    notifications.push_approval_request(tenant_id, approvers_of(tenant_id), approval_id,
                                        tool, requested_by, summary[:200])
    return {"approvalId": approval_id, "status": "PENDING", "paramsHash": p_hash,
            "expiresIn": settings.approval_pending_ttl_seconds}


def get(approval_id: str) -> dict | None:
    row = db.query("SELECT * FROM approval_task WHERE approval_id = %s", (approval_id,), one=True)
    if row is None:
        return None
    # 惰性过期
    if row["status"] == "PENDING" and row["expires_at"].timestamp() < time.time():
        db.execute("UPDATE approval_task SET status = 'EXPIRED' WHERE approval_id = %s", (approval_id,))
        row["status"] = "EXPIRED"
    return _out(row)


def list_for_tenant(tenant_id: str, status: str | None = None) -> list[dict]:
    if status:
        rows = db.query("SELECT * FROM approval_task WHERE tenant_id = %s AND status = %s "
                        "ORDER BY created_at DESC LIMIT 100", (tenant_id, status))
    else:
        rows = db.query("SELECT * FROM approval_task WHERE tenant_id = %s "
                        "ORDER BY created_at DESC LIMIT 100", (tenant_id,))
    return [_out(r) for r in rows]


def decide(approval_id: str, action: str, *, approver_username: str, approver_tenant: str,
           comment: str | None = None) -> dict:
    """审批决定：校验审批人权限（存量域 ap.approval.decide）-> 批准则铸 OT。"""
    task = get(approval_id)
    if task is None:
        raise ApprovalError("GW.APPROVAL_NOT_FOUND", f"审批任务不存在：{approval_id}", 404)
    if task["tenantId"] != approver_tenant:
        raise ApprovalError("GW.TENANT_MISMATCH", "审批人与任务不属于同一租户", 403)
    if task["status"] != "PENDING":
        raise ApprovalError("GW.APPROVAL_STATE_CONFLICT",
                            f"任务状态 {task['status']}，不可再决定", 409, "state_conflict")

    perms = _java_permissions(approver_username)
    if perms is None or "ap.approval.decide" not in perms.get("permissions", []):
        raise ApprovalError("AP.PERMISSION_DENIED", f"用户 {approver_username} 无审批权限（ap.approval.decide）",
                            403, "permission_denied")

    if action == "reject":
        db.execute("UPDATE approval_task SET status = 'REJECTED', approver = %s, decided_at = now(), "
                   "notification = %s WHERE approval_id = %s",
                   (approver_username, comment, approval_id))
        notifications.push_approval_decided(task["tenantId"], task["requestedBy"], approval_id,
                                            task["tool"], False, approver_username)
        return {"approvalId": approval_id, "status": "REJECTED", "approver": approver_username}

    # action == approve：铸一次性令牌 OT（120s，jti 一次性）
    jti = uuid.uuid4().hex
    db.execute("UPDATE approval_task SET status = 'APPROVED', approver = %s, decided_at = now(), "
               "notification = %s WHERE approval_id = %s",
               (approver_username, comment, approval_id))
    db.execute("INSERT INTO one_time_tokens (jti, approval_id, params_hash, expires_at) "
               "VALUES (%s, %s, %s, now() + interval '%s seconds')",
               (jti, approval_id, task["paramsHash"], settings.ot_ttl_seconds))
    ot = ts.mint_ot(task["requestedBy"], approver_username, task["tenantId"], task["tool"],
                    approval_id, task["paramsHash"], jti)
    notifications.push_approval_decided(task["tenantId"], task["requestedBy"], approval_id,
                                        task["tool"], True, approver_username)
    return {"approvalId": approval_id, "status": "APPROVED", "approver": approver_username,
            "oneTimeToken": ot, "expiresIn": settings.ot_ttl_seconds}


def verify_ot(ot_claims: dict, *, tool: str, p_hash: str) -> dict:
    """校验 OT：一次性（jti 未用）+ 未过期 + params_hash 匹配。返回 {username, approver, approvalId}。"""
    if ot_claims.get("azp") != "erp-ai-action" or ot_claims.get("ot_type") != "one_time":
        raise ApprovalError("GW.APPROVAL_TOKEN_EXPIRED", "非一次性审批令牌", 401)
    jti = ot_claims.get("jti")
    row = db.query("SELECT * FROM one_time_tokens WHERE jti = %s", (jti,), one=True) if jti else None
    if row is None or row["used"] or row["expires_at"].timestamp() < time.time():
        raise ApprovalError("GW.APPROVAL_TOKEN_EXPIRED", "一次性令牌无效、已使用或已过期", 401)
    if ot_claims.get("approval_id") != row["approval_id"]:
        raise ApprovalError("GW.APPROVAL_PARAMS_MISMATCH", "OT 与签发记录不符", 409)
    if ot_claims.get("scope") != [tool]:
        raise ApprovalError("GW.APPROVAL_PARAMS_MISMATCH", f"OT scope 不覆盖工具 {tool}", 409)
    if ot_claims.get("params_hash") != p_hash:
        raise ApprovalError("GW.APPROVAL_PARAMS_MISMATCH",
                            "审批参数与本次请求不一致（params_hash 校验失败）", 409)
    sub = ot_claims.get("sub", "")
    return {"username": sub[2:] if sub.startswith("u-") else sub,
            "approver": ot_claims.get("approver"),
            "approvalId": ot_claims.get("approval_id"),
            "tenantId": ot_claims.get("tid")}


def consume_ot(ot_claims: dict) -> None:
    """标记 OT 已用 + 任务 CONSUMED（与工具调用结果无关——OT 只能用一次）。"""
    jti = ot_claims.get("jti")
    db.execute("UPDATE one_time_tokens SET used = TRUE, used_at = now() WHERE jti = %s", (jti,))
    db.execute("UPDATE approval_task SET status = 'CONSUMED' WHERE approval_id = %s AND status = 'APPROVED'",
               (ot_claims.get("approval_id"),))


def _java_permissions(username: str) -> dict | None:
    try:
        resp = httpx.get(f"{settings.erp_ap_base}/internal/permissions",
                         params={"username": username},
                         headers={"X-Internal-Secret": settings.internal_secret}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except httpx.HTTPError:
        pass
    return None


def _out(r: dict) -> dict:
    return {
        "approvalId": r["approval_id"], "tenantId": r["tenant_id"], "scene": r["scene"],
        "agentId": r["agent_id"], "tool": r["tool"],
        "params": _load(r["params"]), "paramsHash": r["params_hash"],
        "requestedBy": r["requested_by"], "status": r["status"], "approver": r["approver"],
        "decidedAt": r["decided_at"].isoformat() if r["decided_at"] else None,
        "rationale": r["rationale"], "impact": r["impact"],
        "snapshot": _load(r["snapshot"]),
        "createdAt": r["created_at"].isoformat(),
        "expiresAt": r["expires_at"].isoformat(),
    }


def _load(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value
