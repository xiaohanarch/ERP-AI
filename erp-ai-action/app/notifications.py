"""通知：审批请求 / 事件诊断结果 / 代理吊销（WorkBuddy 通知中心消费）。"""
from __future__ import annotations

from app import db


def push(tenant_id: str | None, username: str, kind: str, title: str,
         body: str | None = None, ref_id: str | None = None) -> None:
    db.execute(
        "INSERT INTO notifications (tenant_id, username, kind, title, body, ref_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (tenant_id, username, kind, title, body, ref_id))


def push_approval_request(tenant_id: str, approvers: list[str], approval_id: str,
                          tool: str, requested_by: str, summary: str) -> None:
    for who in approvers:
        push(tenant_id, who, "APPROVAL_REQUEST",
             f"审批请求：{tool}",
             f"{requested_by} 发起的操作等待您批准。{summary}",
             approval_id)


def push_approval_decided(tenant_id: str, requested_by: str, approval_id: str,
                          tool: str, approved: bool, approver: str) -> None:
    outcome = "已批准" if approved else "已拒绝"
    push(tenant_id, requested_by, "APPROVAL_DECIDED",
         f"审批{outcome}：{tool}",
         f"审批人 {approver} {outcome}了您的请求（{approval_id}）。",
         approval_id)


def push_event_diag(tenant_id: str, username: str, invoice_no: str, summary: str) -> None:
    push(tenant_id, username, "EVENT_DIAG",
         f"阻断发票自动诊断完成：{invoice_no}",
         summary, invoice_no)


def list_for(username: str, unread_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM notifications WHERE username = %s"
    if unread_only:
        sql += " AND NOT read"
    sql += " ORDER BY id DESC LIMIT 100"
    rows = db.query(sql, (username,))
    out = []
    for r in rows:
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"],
                    "refId": r["ref_id"], "read": r["read"],
                    "createdAt": r["created_at"].isoformat()})
    return out


def mark_read(username: str, notification_id: int) -> bool:
    row = db.query("SELECT id FROM notifications WHERE id = %s AND username = %s",
                   (notification_id, username), one=True)
    if row is None:
        return False
    db.execute("UPDATE notifications SET read = TRUE WHERE id = %s", (notification_id,))
    return True
