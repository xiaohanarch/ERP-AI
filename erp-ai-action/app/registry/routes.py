"""注册中心路由（admin / 内部服务专用）。

- POST /gw/agents                  注册（SoD 注册期校验）
- GET  /gw/agents                  清册（Roster，审计/自检用）
- POST /gw/agents/{id}/revoke      吊销（对既有 T2 即时生效——下次调用 401）
- POST /gw/agents/{id}/restore     恢复（演示复位用）
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import audit
from app.errors import gw_json, unauthorized
from app.registry import service
from app.security import is_admin

router = APIRouter()


@router.post("/gw/agents")
def register_agent(request: Request, body: dict):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    try:
        result = service.register(
            str(body.get("agentId", "")), str(body.get("displayName", "")),
            str(body.get("appid", "erp-ai-hub")), str(body.get("tenantId", "")),
            body.get("tools") or [], body.get("owner"))
    except service.RegistryError as e:
        status = 403 if e.code == "GW.SOD_CONFLICT" else 400
        return gw_json(status, e.code, e.message, "gateway_policy" if e.code.startswith("GW.") else "validation_error")
    audit.record(action="agent.register", outcome="SUCCESS", agent_id=result["agentId"],
                 detail={"tools": result["tools"]})
    return result


@router.get("/gw/agents")
def roster(request: Request, tenant_id: str | None = None):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    agents = service.list_agents(tenant_id)
    audit.record(action="agent.roster.view", outcome="SUCCESS", tenant_id=tenant_id,
                 detail={"count": len(agents)})
    return {"count": len(agents), "agents": agents}


@router.post("/gw/agents/{agent_id}/revoke")
def revoke_agent(agent_id: str, request: Request):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    try:
        result = service.revoke(agent_id)
    except service.RegistryError as e:
        return gw_json(404 if e.code == "GW.AGENT_NOT_REGISTERED" else 400, e.code, e.message, "gateway_policy")
    audit.record(action="agent.revoke", outcome="SUCCESS", agent_id=agent_id)
    return result


@router.post("/gw/agents/{agent_id}/restore")
def restore_agent(agent_id: str, request: Request):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    try:
        result = service.restore(agent_id)
    except service.RegistryError as e:
        return gw_json(404 if e.code == "GW.AGENT_NOT_REGISTERED" else 400, e.code, e.message, "gateway_policy")
    audit.record(action="agent.restore", outcome="SUCCESS", agent_id=agent_id)
    return result
