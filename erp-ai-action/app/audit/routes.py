"""审计与证据路由。

- GET /internal/audit           审计查询（X-Internal-Secret；评测/自检/报告用）
- GET /gw/evidence/export       租户证据包导出（admin/internal；导出本身留痕）
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import audit
from app.errors import unauthorized
from app.security import is_admin, is_internal

router = APIRouter()


@router.get("/internal/audit")
def audit_query(request: Request, tenant_id: str | None = None, agent_id: str | None = None,
                user_id: str | None = None, action: str | None = None, outcome: str | None = None,
                approval_id: str | None = None, trace_id: str | None = None, limit: int = 200):
    if not is_internal(request):
        return unauthorized("需要 X-Internal-Secret")
    rows = audit.query(tenant_id=tenant_id, agent_id=agent_id, user_id=user_id, action=action,
                       outcome=outcome, approval_id=approval_id, trace_id=trace_id, limit=limit)
    return {"count": len(rows), "items": rows}


@router.get("/gw/evidence/export")
def evidence_export(request: Request, tenant_id: str, hours: int = 24):
    if not is_admin(request):
        return unauthorized("需要 admin（HTTP Basic）或内部密钥")
    package = audit.export_evidence(tenant_id, hours)
    body = json.dumps(package, ensure_ascii=False, indent=2)
    return JSONResponse(content=json.loads(body),
                        headers={"Content-Disposition": f'attachment; filename="evidence-{tenant_id}.json"'})
