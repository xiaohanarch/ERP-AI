"""成本路由。

- GET /internal/cost      明细查询（X-Internal-Secret；租检/报告用）
- GET /gw/cost/summary    四维汇总 + 审计对账（admin）
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import db
from app.cost import service
from app.errors import unauthorized
from app.security import is_admin, is_internal

router = APIRouter()


@router.get("/internal/cost")
def cost_detail(request: Request, tenant_id: str | None = None, scene: str | None = None,
                agent_id: str | None = None, limit: int = 200):
    if not is_internal(request):
        return unauthorized("需要 X-Internal-Secret")
    sql = "SELECT * FROM cost_ledger WHERE 1=1"
    params: list = []
    for col, val in [("tenant_id", tenant_id), ("scene", scene), ("agent_id", agent_id)]:
        if val:
            sql += f" AND {col} = %s"
            params.append(val)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(min(limit, 1000))
    rows = db.query(sql, tuple(params))
    items = []
    for r in rows:
        items.append({"ts": r["ts"].isoformat(), "tenantId": r["tenant_id"],
                      "agentId": r["agent_id"], "scene": r["scene"], "userId": r["user_id"],
                      "model": r["model"], "promptTokens": r["prompt_tokens"],
                      "completionTokens": r["completion_tokens"], "totalTokens": r["total_tokens"],
                      "traceId": r["trace_id"]})
    if tenant_id:
        return {"summary": service.tenant_summary(tenant_id), "items": items}
    return {"count": len(items), "items": items}


@router.get("/gw/cost/summary")
def cost_summary(request: Request):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    return service.summary_all()
