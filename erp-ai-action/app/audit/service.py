"""审计五要素：谁（用户/代理）、做了什么（动作/工具）、何时、结果、依据（委托链/审批引用）。

观测与审计一次采集两用：同一调用链上的 span 与 audit_log 以 trace_id 关联。
"""
from __future__ import annotations

import json

from app import db
from app.mcp.tool_registry import tool_registry


def record(*, action: str, outcome: str, tenant_id: str | None = None,
           user_id: str | None = None, agent_id: str | None = None, azp: str | None = None,
           http_status: int | None = None, error_code: str | None = None,
           scene: str | None = None, approval_id: str | None = None,
           approver: str | None = None, delegation_chain: dict | list | None = None,
           trace_id: str | None = None, detail: dict | None = None) -> None:
    """写入审计（best-effort：审计失败不阻断主流程，但必须打日志）。"""
    chain_json = json.dumps(delegation_chain, ensure_ascii=False) if delegation_chain else None
    detail_json = json.dumps(detail, ensure_ascii=False) if detail else None
    try:
        db.execute(
            "INSERT INTO audit_log (tenant_id, user_id, agent_id, azp, action, outcome, http_status, "
            "error_code, scene, approval_id, approver, delegation_chain, trace_id, detail) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant_id, user_id, agent_id, azp, action, outcome, http_status, error_code,
             scene, approval_id, approver, chain_json, trace_id, detail_json))
    except Exception as e:  # noqa: BLE001
        print(f"[audit] 写入失败 action={action}: {e}", flush=True)


def query(*, tenant_id: str | None = None, agent_id: str | None = None,
          user_id: str | None = None, action: str | None = None, outcome: str | None = None,
          approval_id: str | None = None, trace_id: str | None = None,
          limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []
    for col, val in [("tenant_id", tenant_id), ("agent_id", agent_id), ("user_id", user_id),
                     ("action", action), ("outcome", outcome), ("approval_id", approval_id),
                     ("trace_id", trace_id)]:
        if val:
            sql += f" AND {col} = %s"
            params.append(val)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(min(limit, 1000))
    rows = db.query(sql, tuple(params))
    return [_row_out(r) for r in rows]


def _row_out(r: dict) -> dict:
    out = dict(r)
    for k in ("ts",):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    for k in ("delegation_chain", "detail"):
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except ValueError:
                pass
    return out


def export_evidence(tenant_id: str, hours: int = 24) -> dict:
    """证据包导出（导出本身留痕）：版本戳 + Agent 清册 + 审批留痕 + 审计摘录 + 成本汇总。"""
    from app import cost as cost_mod
    from app.registry import service as registry

    agents = registry.list_agents(tenant_id)
    approvals = db.query(
        "SELECT * FROM approval_task WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 100", (tenant_id,))
    approvals_out = []
    for a in approvals:
        approvals_out.append({
            "approvalId": a["approval_id"], "scene": a["scene"], "agentId": a["agent_id"],
            "tool": a["tool"], "requestedBy": a["requested_by"], "status": a["status"],
            "approver": a["approver"],
            "decidedAt": a["decided_at"].isoformat() if a["decided_at"] else None,
            "rationale": a["rationale"], "impact": a["impact"],
            "snapshot": _load_json(a["snapshot"]), "createdAt": a["created_at"].isoformat(),
        })
    audits = query(tenant_id=tenant_id, limit=200)
    cost_summary = cost_mod.tenant_summary(tenant_id)
    package = {
        "tenantId": tenant_id,
        "generatedAt": _now_iso(),
        "versions": tool_registry.versions(),
        "agents": agents,
        "approvals": approvals_out,
        "auditExcerpt": audits,
        "costSummary": cost_summary,
    }
    # 导出留痕（审计包含导出动作本身）
    record(tenant_id=tenant_id, action="evidence.export", outcome="SUCCESS",
           detail={"hours": hours, "auditRows": len(audits), "approvals": len(approvals_out)})
    return package


def _load_json(value: str | None):
    if value is None:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
