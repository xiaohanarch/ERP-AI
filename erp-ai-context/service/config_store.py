"""租户配置存储：语义叠加从「文件级」升为「数据级」（产品化配置界面后端）。

语义：
  - 文件层（overlays/*.yaml）= 标品出厂默认；
  - DB 层（sem_tenant_config）= 租户当前配置：首次写入时从文件播种整份叠加，
    此后以 DB 为准（PUT 按字段合并）；DELETE 即恢复出厂（回落文件层）；
  - 每次变更写 sem_config_change_log（who / when / what），管理端可查。

可用性：未配置 DATABASE_URL 或库不可达时存储禁用 —— 全部回落文件层，
语义工具只读照常工作；管理端写接口返回 503（SEMANTIC.CONFIG_STORE_DISABLED）。
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager

import psycopg2.pool

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool: "psycopg2.pool.SimpleConnectionPool | None" = None
_disabled_reason: str | None = None


def enabled() -> bool:
    return bool(DATABASE_URL) and _disabled_reason is None


def reason() -> str | None:
    return _disabled_reason


@contextmanager
def _conn():
    """从池取连接，用毕归还（异常回滚）——psycopg2 连接的 with 语义是关连接不是归还，不可用。"""
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def init() -> None:
    """启动期建表（best-effort：库不可达则禁用存储，服务继续以文件层运行）。"""
    global _pool, _disabled_reason
    if not DATABASE_URL:
        _disabled_reason = "未配置 DATABASE_URL"
        print("[config-store] 未配置 DATABASE_URL：租户配置回落文件层", flush=True)
        return
    try:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 4, DATABASE_URL)
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sem_tenant_config (
                        tenant_id   TEXT PRIMARY KEY,
                        config      TEXT NOT NULL,
                        version     INTEGER NOT NULL DEFAULT 1,
                        updated_by  TEXT,
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sem_config_change_log (
                        id        SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        actor     TEXT,
                        action    TEXT NOT NULL,
                        patch     TEXT,
                        version   INTEGER,
                        ts        TIMESTAMPTZ NOT NULL DEFAULT now()
                    )""")
        print("[config-store] 租户配置存储就绪（DB 层优先，文件层为出厂默认）", flush=True)
    except Exception as e:  # noqa: BLE001 —— 存储不可用不阻断语义服务
        _disabled_reason = str(e)[:120]
        _pool = None
        print(f"[config-store] 初始化失败，回落文件层：{e}", flush=True)


def get_stored(tenant_id: str) -> dict | None:
    """DB 层当前配置（无记录返回 None = 文件层生效）。"""
    if not enabled():
        return None
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT config, version, updated_by, updated_at "
                        "FROM sem_tenant_config WHERE tenant_id = %s", (tenant_id,))
            row = cur.fetchone()
    if row is None:
        return None
    return {"config": json.loads(row[0]), "version": row[1],
            "updatedBy": row[2], "updatedAt": row[3].isoformat() if row[3] else None}


def apply_patch(tenant_id: str, patch: dict, actor: str, file_overlay: dict | None) -> dict:
    """按字段合并写入：无 DB 记录时先以文件叠加播种（出厂默认），version+1，记变更。"""
    if not enabled():
        raise RuntimeError("config store disabled")
    stored = get_stored(tenant_id)
    base = (stored or {}).get("config")
    if base is None:
        base = dict(file_overlay or {})
        base.pop("tenant_id", None)
        base.pop("version", None)
        base.pop("description", None)
        base["tenant_id"] = tenant_id
    merged = _merge(base, patch)
    version = (stored["version"] + 1) if stored else 1
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sem_tenant_config (tenant_id, config, version, updated_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    config = EXCLUDED.config, version = EXCLUDED.version,
                    updated_by = EXCLUDED.updated_by, updated_at = now()
                """, (tenant_id, json.dumps(merged, ensure_ascii=False), version, actor))
            cur.execute("""
                INSERT INTO sem_config_change_log (tenant_id, actor, action, patch, version)
                VALUES (%s, %s, 'update', %s, %s)
                """, (tenant_id, actor, json.dumps(patch, ensure_ascii=False), version))
    return {"config": merged, "version": version, "updatedBy": actor, "source": "db"}


def reset(tenant_id: str, actor: str) -> bool:
    """恢复出厂：删除 DB 记录（回落文件层），记变更。"""
    if not enabled():
        raise RuntimeError("config store disabled")
    existed = get_stored(tenant_id) is not None
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sem_tenant_config WHERE tenant_id = %s", (tenant_id,))
            cur.execute("""
                INSERT INTO sem_config_change_log (tenant_id, actor, action, patch, version)
                VALUES (%s, %s, 'reset', NULL, NULL)
                """, (tenant_id, actor))
    return existed


def changes(tenant_id: str, limit: int = 20) -> list[dict]:
    if not enabled():
        return []
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, actor, action, patch, version, ts "
                        "FROM sem_config_change_log WHERE tenant_id = %s "
                        "ORDER BY id DESC LIMIT %s", (tenant_id, limit))
            rows = cur.fetchall()
    return [{"id": r[0], "actor": r[1], "action": r[2],
             "patch": json.loads(r[3]) if r[3] else None,
             "version": r[4], "ts": r[5].isoformat() if r[5] else None} for r in rows]


def _merge(base: dict, patch: dict) -> dict:
    """字段级合并：industry 覆盖；parameters/metrics 按键合并；terms 整表替换。"""
    out = dict(base)
    if "industry" in patch:
        out["industry"] = patch["industry"]
    for key in ("parameters", "metrics"):
        if isinstance(patch.get(key), dict):
            merged = dict(out.get(key) or {})
            merged.update(patch[key])
            out[key] = merged
    if isinstance(patch.get("terms"), list):
        out["terms"] = patch["terms"]
    return out
