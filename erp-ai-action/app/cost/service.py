"""成本台账：tenant/agent/scene/user 四维 token 计量（全部经模型网关归集）。"""
from __future__ import annotations

from app import db


def record_usage(*, tenant_id: str | None, agent_id: str | None, scene: str | None,
                 user_id: str | None, model: str, prompt_tokens: int, completion_tokens: int,
                 trace_id: str | None = None) -> None:
    db.execute(
        "INSERT INTO cost_ledger (tenant_id, agent_id, scene, user_id, model, "
        "prompt_tokens, completion_tokens, total_tokens, trace_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (tenant_id, agent_id, scene, user_id, model,
         prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, trace_id))


def tenant_summary(tenant_id: str) -> dict:
    row = db.query(
        "SELECT count(*) AS calls, coalesce(sum(prompt_tokens),0) AS prompt_tokens, "
        "coalesce(sum(completion_tokens),0) AS completion_tokens, "
        "coalesce(sum(total_tokens),0) AS total_tokens FROM cost_ledger WHERE tenant_id = %s",
        (tenant_id,), one=True)
    by_scene = db.query(
        "SELECT scene, count(*) AS calls, coalesce(sum(total_tokens),0) AS total_tokens "
        "FROM cost_ledger WHERE tenant_id = %s GROUP BY scene ORDER BY calls DESC", (tenant_id,))
    by_agent = db.query(
        "SELECT agent_id, count(*) AS calls, coalesce(sum(total_tokens),0) AS total_tokens "
        "FROM cost_ledger WHERE tenant_id = %s GROUP BY agent_id ORDER BY calls DESC", (tenant_id,))
    return {
        "calls": row["calls"], "promptTokens": row["prompt_tokens"],
        "completionTokens": row["completion_tokens"], "totalTokens": row["total_tokens"],
        "byScene": [dict(r) for r in by_scene],
        "byAgent": [dict(r) for r in by_agent],
    }


def summary_all() -> dict:
    rows = db.query(
        "SELECT tenant_id, count(*) AS calls, coalesce(sum(total_tokens),0) AS total_tokens "
        "FROM cost_ledger GROUP BY tenant_id ORDER BY tenant_id")
    by_tenant = {r["tenant_id"]: {"calls": r["calls"], "totalTokens": r["total_tokens"]} for r in rows}
    # 与审计对账（model_call 事件数 vs 台账行数）
    audit_rows = db.query(
        "SELECT tenant_id, count(*) AS n FROM audit_log WHERE action = 'model_call' "
        "GROUP BY tenant_id")
    audit_by_tenant = {r["tenant_id"]: r["n"] for r in audit_rows}
    reconciliation = {}
    for tenant in set(by_tenant) | set(audit_by_tenant):
        cost_calls = by_tenant.get(tenant, {}).get("calls", 0)
        audit_calls = audit_by_tenant.get(tenant, 0)
        reconciliation[tenant] = {"costCalls": cost_calls, "auditModelCalls": audit_calls,
                                  "match": cost_calls == audit_calls}
    return {"byTenant": by_tenant, "reconciliation": reconciliation}
