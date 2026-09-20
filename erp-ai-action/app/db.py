"""ai_gw 数据库：连接池 + schema 初始化 + 种子（Agent 注册中心 / 服务客户 / 审批人映射）。"""
from __future__ import annotations

import json
import threading

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

from app.config import settings

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_init_lock = threading.Lock()


class Db:
    """轻量连接池封装：每次操作借还连接，线程安全（FastAPI 同步路由跑线程池）。"""

    def __enter__(self):
        self.conn = _pool.getconn()
        self.conn.autocommit = False
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        _pool.putconn(self.conn)


def query(sql: str, params: tuple = (), *, one: bool = False) -> list[dict] | dict | None:
    with Db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, params: tuple = ()) -> None:
    with Db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def init() -> None:
    global _pool
    with _init_lock:
        if _pool is not None:
            return
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, settings.database_url)
        with Db() as conn:
            with conn.cursor() as cur:
                for ddl in _DDL:
                    cur.execute(ddl)
        _seed()


# ---------------------------------------------------------------- schema
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS agents (
        agent_id     TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        appid        TEXT NOT NULL,
        tenant_id    TEXT NOT NULL,
        tools        TEXT NOT NULL DEFAULT '[]',
        status       TEXT NOT NULL DEFAULT 'ACTIVE',
        revoked_at   TIMESTAMPTZ,
        owner        TEXT,
        delegates_to TEXT NOT NULL DEFAULT '[]',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # 存量库补列（协作清单：跨域委派的目标代理白名单，声明式种子拥有）
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS delegates_to TEXT NOT NULL DEFAULT '[]'",
    """
    CREATE TABLE IF NOT EXISTS subscriptions (
        subscription_id TEXT PRIMARY KEY,
        tenant_id       TEXT NOT NULL,
        topic           TEXT NOT NULL,
        endpoint_url    TEXT NOT NULL,
        secret          TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'ACTIVE',
        revoked_at      TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS service_clients (
        client_id     TEXT PRIMARY KEY,
        client_secret TEXT NOT NULL,
        kind          TEXT NOT NULL,
        redirect_uris TEXT NOT NULL DEFAULT '[]',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approval_task (
        approval_id    TEXT PRIMARY KEY,
        tenant_id      TEXT NOT NULL,
        scene          TEXT,
        agent_id       TEXT,
        tool           TEXT NOT NULL,
        params         TEXT NOT NULL,
        params_hash    TEXT NOT NULL,
        requested_by   TEXT NOT NULL,
        idempotency_key TEXT,
        rationale      TEXT,
        impact         TEXT,
        snapshot       TEXT,
        status         TEXT NOT NULL,
        approver       TEXT,
        decided_at     TIMESTAMPTZ,
        notification   TEXT,
        trace_id       TEXT,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at     TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS one_time_tokens (
        jti        TEXT PRIMARY KEY,
        approval_id TEXT NOT NULL,
        params_hash TEXT NOT NULL,
        used       BOOLEAN NOT NULL DEFAULT FALSE,
        used_at    TIMESTAMPTZ,
        expires_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id       BIGSERIAL PRIMARY KEY,
        ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
        tenant_id TEXT,
        user_id  TEXT,
        agent_id TEXT,
        azp      TEXT,
        action   TEXT NOT NULL,
        outcome  TEXT NOT NULL,
        http_status INT,
        error_code TEXT,
        scene    TEXT,
        approval_id TEXT,
        approver TEXT,
        delegation_chain TEXT,
        trace_id TEXT,
        detail   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cost_ledger (
        id       BIGSERIAL PRIMARY KEY,
        ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
        tenant_id TEXT,
        agent_id TEXT,
        scene    TEXT,
        user_id  TEXT,
        model    TEXT,
        prompt_tokens INT NOT NULL DEFAULT 0,
        completion_tokens INT NOT NULL DEFAULT 0,
        total_tokens INT NOT NULL DEFAULT 0,
        trace_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_codes (
        code        TEXT PRIMARY KEY,
        client_id   TEXT NOT NULL,
        username    TEXT NOT NULL,
        tenant_id   TEXT NOT NULL,
        display_name TEXT,
        redirect_uri TEXT,
        expires_at  TIMESTAMPTZ NOT NULL,
        used        BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id       BIGSERIAL PRIMARY KEY,
        tenant_id TEXT,
        username TEXT NOT NULL,
        kind     TEXT NOT NULL,
        title    TEXT NOT NULL,
        body     TEXT,
        ref_id   TEXT,
        read     BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_cache (
        cache_key   TEXT PRIMARY KEY,
        tenant_id   TEXT,
        agent_id    TEXT,
        tool        TEXT NOT NULL,
        response    TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at  TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON audit_log (tenant_id, ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_cost_tenant_ts ON cost_ledger (tenant_id, ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_task (tenant_id, status)",
]


# ---------------------------------------------------------------- 种子
_READ_TOOLS = [
    "ap.invoice.checkValidation", "ap.invoice.getMatchDetail",
    "ap.invoice.getDerivedField", "ap.invoice.listBlocked", "ap.balance.query",
]
_SEMANTIC_TOOLS = [
    "semantic.metadata.entities", "semantic.metadata.fields", "semantic.metric.get",
    "semantic.term.translate", "semantic.task.match", "semantic.operation.explain",
    "semantic.capability.discover", "semantic.drift.status",
]
_TAX_TOOLS = ["ap.invoice.applyTaxCode"]

_PROC_TOOLS = ["proc.po.getDetail", "proc.gr.listForPo"]

_SEED_AGENTS = [
    # (agent_id, display_name, tenant, tools, owner, delegates_to)
    ("ap-copilot", "AP 诊断 Copilot（页面内嵌）", "T-EAST",
     _READ_TOOLS + _TAX_TOOLS + _SEMANTIC_TOOLS, "lisi", ["proc-copilot"]),
    ("proc-copilot", "采购查询 Copilot（跨域协同标的）", "T-EAST", _PROC_TOOLS, "lisi", []),
    ("ap-batch", "AP 批量筛查助手", "T-EAST",
     ["ap.invoice.listBlocked", "ap.balance.query", "semantic.term.translate", "semantic.task.match",
      "semantic.metric.get", "semantic.metadata.fields"], "lisi", []),
    ("ap-headless", "AP 无头脚本代理（形态③）", "T-EAST", _READ_TOOLS, "zhangsan", []),
    ("event-diag", "AP 事件触发诊断代理（形态④）", "T-EAST",
     ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail"], "lisi", []),
    ("uni-copilot", "AP 诊断 Copilot（星联科技）", "T-UNI", _READ_TOOLS + _TAX_TOOLS + _SEMANTIC_TOOLS, "qianqi", []),
    ("uni-batch", "AP 批量筛查助手（星联科技）", "T-UNI",
     ["ap.invoice.listBlocked", "ap.balance.query", "semantic.term.translate", "semantic.task.match",
      "semantic.metric.get", "semantic.metadata.fields"], "qianqi", []),
]

_SEED_CLIENTS = [
    # (client_id, secret, kind, redirect_uris)
    ("erp-ai-hub", settings.hub_client_secret, "backend", []),
    ("workbuddy", "workbuddy-demo-secret", "surface", ["http://localhost:8088/callback"]),
]


def _seed() -> None:
    with Db() as conn:
        with conn.cursor() as cur:
            for agent_id, display, tenant, tools, owner, delegates_to in _SEED_AGENTS:
                cur.execute(
                    "INSERT INTO agents (agent_id, display_name, appid, tenant_id, tools, owner, delegates_to) "
                    "VALUES (%s, %s, 'erp-ai-hub', %s, %s, %s, %s) "
                    "ON CONFLICT (agent_id) DO UPDATE SET tools = EXCLUDED.tools, "
                    "delegates_to = EXCLUDED.delegates_to",
                    (agent_id, display, tenant, json.dumps(tools), owner, json.dumps(delegates_to)))
            for client_id, secret, kind, uris in _SEED_CLIENTS:
                cur.execute(
                    "INSERT INTO service_clients (client_id, client_secret, kind, redirect_uris) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (client_id) DO NOTHING",
                    (client_id, secret, kind, json.dumps(uris)))
