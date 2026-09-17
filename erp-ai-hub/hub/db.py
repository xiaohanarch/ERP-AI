"""Hub 数据库：审批等待映射（approvalId -> thread）+ 资产解析留痕。"""
from __future__ import annotations

import json
import threading

import psycopg

from hub.config import settings

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS approval_wait (
        approval_id    TEXT PRIMARY KEY,
        thread_id      TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        scene          TEXT,
        tenant_id      TEXT,
        user_id        TEXT,
        suggestion     JSONB,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS resolution_log (
        id             BIGSERIAL PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        scene          TEXT,
        tenant_id      TEXT,
        resolution     JSONB NOT NULL,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_resolution_conv ON resolution_log (conversation_id, id DESC)",
]

_lock = threading.Lock()
_conn: psycopg.Connection | None = None


def _connection() -> psycopg.Connection:
    global _conn
    with _lock:
        if _conn is None or _conn.closed:
            _conn = psycopg.connect(settings.database_url, autocommit=True)
            with _conn.cursor() as cur:
                for ddl in _DDL:
                    cur.execute(ddl)
        return _conn


def save_wait(approval_id: str, thread_id: str, conversation_id: str, scene: str,
              tenant_id: str, user_id: str, suggestion: dict) -> None:
    with _connection().cursor() as cur:
        cur.execute(
            "INSERT INTO approval_wait (approval_id, thread_id, conversation_id, scene, "
            "tenant_id, user_id, suggestion) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (approval_id) DO NOTHING",
            (approval_id, thread_id, conversation_id, scene, tenant_id, user_id,
             json.dumps(suggestion, ensure_ascii=False)))


def load_wait(approval_id: str) -> dict | None:
    with _connection().cursor() as cur:
        cur.execute("SELECT approval_id, thread_id, conversation_id, scene, tenant_id, user_id, "
                    "suggestion FROM approval_wait WHERE approval_id = %s", (approval_id,))
        row = cur.fetchone()
    if row is None:
        return None
    cols = ["approvalId", "threadId", "conversationId", "scene", "tenantId", "userId", "suggestion"]
    return dict(zip(cols, row, strict=True))


def wait_by_thread(thread_id: str) -> dict | None:
    with _connection().cursor() as cur:
        cur.execute("SELECT approval_id FROM approval_wait WHERE thread_id = %s "
                    "ORDER BY created_at DESC LIMIT 1", (thread_id,))
        row = cur.fetchone()
    return {"approvalId": row[0]} if row else None


def delete_wait(approval_id: str) -> None:
    """审批终结（完成/拒绝/失败）后清除挂起映射，恢复会话可用。"""
    with _connection().cursor() as cur:
        cur.execute("DELETE FROM approval_wait WHERE approval_id = %s", (approval_id,))


def log_resolution(conversation_id: str, scene: str, tenant_id: str, resolution: dict) -> None:
    with _connection().cursor() as cur:
        cur.execute(
            "INSERT INTO resolution_log (conversation_id, scene, tenant_id, resolution) "
            "VALUES (%s,%s,%s,%s)",
            (conversation_id, scene, tenant_id, json.dumps(resolution, ensure_ascii=False)))


def resolutions(conversation_id: str, limit: int = 20) -> list[dict]:
    with _connection().cursor() as cur:
        cur.execute("SELECT conversation_id, scene, tenant_id, resolution, created_at "
                    "FROM resolution_log WHERE conversation_id = %s ORDER BY id DESC LIMIT %s",
                    (conversation_id, limit))
        rows = cur.fetchall()
    return [
        {"conversationId": r[0], "scene": r[1], "tenantId": r[2], "resolution": r[3],
         "createdAt": r[4].isoformat()} for r in rows]
