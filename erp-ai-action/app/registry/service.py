"""Agent 注册中心：注册/清册/吊销/恢复 + SoD 互斥（注册期与运行期双重校验）。"""
from __future__ import annotations

import json

from app import db
from app.config import settings
from app.mcp.tool_registry import tool_registry


class RegistryError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def get_agent(agent_id: str) -> dict | None:
    return db.query("SELECT * FROM agents WHERE agent_id = %s", (agent_id,), one=True)


def list_agents(tenant_id: str | None = None) -> list[dict]:
    if tenant_id:
        rows = db.query("SELECT * FROM agents WHERE tenant_id = %s ORDER BY created_at", (tenant_id,))
    else:
        rows = db.query("SELECT * FROM agents ORDER BY created_at")
    result = []
    for r in rows:
        result.append({
            "agentId": r["agent_id"], "displayName": r["display_name"], "appid": r["appid"],
            "tenantId": r["tenant_id"], "tools": json.loads(r["tools"]), "status": r["status"],
            "revokedAt": r["revoked_at"].isoformat() if r["revoked_at"] else None,
            "owner": r["owner"],
            "sodGroups": sorted(tool_registry.sod_groups_of(json.loads(r["tools"]))),
            "createdAt": r["created_at"].isoformat(),
        })
    return result


def register(agent_id: str, display_name: str, appid: str, tenant_id: str,
             tools: list[str], owner: str | None = None) -> dict:
    agent_id = agent_id.strip()
    if not agent_id or not display_name or not appid or not tenant_id:
        raise RegistryError("AP.VALIDATION_ERROR", "agentId/displayName/appid/tenantId 必填")
    if not isinstance(tools, list) or not tools:
        raise RegistryError("AP.VALIDATION_ERROR", "tools 必须为非空数组")

    known = tool_registry.known_tools()
    unknown = [t for t in tools if t not in known]
    if unknown:
        raise RegistryError("AP.VALIDATION_ERROR", f"未知工具（不在规格/语义清单中）：{unknown}")

    conflict = sod_conflict_of(tools)
    if conflict:
        raise RegistryError("GW.SOD_CONFLICT", f"SoD 互斥：同一代理不得同时持有 {conflict}")

    existing = get_agent(agent_id)
    if existing is not None:
        raise RegistryError("AP.VALIDATION_ERROR", f"代理已注册：{agent_id}")

    db.execute(
        "INSERT INTO agents (agent_id, display_name, appid, tenant_id, tools, owner) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (agent_id, display_name, appid, tenant_id, json.dumps(sorted(set(tools))), owner))
    return {"agentId": agent_id, "status": "ACTIVE", "tools": sorted(set(tools))}


def revoke(agent_id: str) -> dict:
    row = get_agent(agent_id)
    if row is None:
        raise RegistryError("GW.AGENT_NOT_REGISTERED", f"代理未注册：{agent_id}")
    db.execute("UPDATE agents SET status = 'REVOKED', revoked_at = now() WHERE agent_id = %s", (agent_id,))
    return {"agentId": agent_id, "status": "REVOKED", "revokedAt": _now_iso()}


def restore(agent_id: str) -> dict:
    row = get_agent(agent_id)
    if row is None:
        raise RegistryError("GW.AGENT_NOT_REGISTERED", f"代理未注册：{agent_id}")
    db.execute("UPDATE agents SET status = 'ACTIVE', revoked_at = NULL WHERE agent_id = %s", (agent_id,))
    return {"agentId": agent_id, "status": "ACTIVE"}


def sod_conflict_of(tools: list[str]) -> list[str] | None:
    """工具集合命中任一互斥组对 -> 返回冲突组名列表。"""
    groups = tool_registry.sod_groups_of(tools)
    for a, b in settings.sod_conflicts:
        if a in groups and b in groups:
            return [a, b]
    return None


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
