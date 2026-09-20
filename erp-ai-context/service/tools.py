"""七个语义查询工具（网关契约：POST /tools/{name} -> {tool, result, _meta}）。

  semantic.metadata.entities   实体清单（投影段术语 + 实时元数据合并）
  semantic.metadata.fields     实体字段（存量字段实时取 + 派生字段标注来源）
  semantic.metric.get          派生指标口径（A0 租户叠加，阈值来源取证）
  semantic.term.translate      业务术语 -> 语义实体（租户叠加优先，回退 Standard）
  semantic.task.match          能力问题清单匹配（30 条锚点）
  semantic.operation.explain   BO 操作解释（规格即工具：读 bo-ap.yaml x-bo-*）
  semantic.drift.status        漂移检测（增量段 vs 元数据现状）

每个工具返回 (result, sourceLayer)；sourceLayer ∈ standard | partner | tenant（partner = 行业语义包）。
"""
from __future__ import annotations

import re

from drift import drift_check
from service import loader


class ToolError(ValueError):
    """参数/引用错误（main.py 转 400 语义错误信封）。"""


# ---------------------------------------------------------------- 工具实现

def tool_metadata_entities(args: dict, tenant: str | None) -> tuple[dict, str]:
    """实体清单：投影段（生成基础层 + 人工口径层，元数据自动喂养）。"""
    sem = loader.load_semantics()
    live = loader.live_metadata()
    proj = loader.effective_projection()

    result = {
        "domain": sem.get("domain"),
        "description": sem.get("description"),
        "entities": proj.get("entities", []),
        "dimensions": proj.get("dimensions", []),
        "enums": proj.get("enums", []),
        "operations": sem.get("native", {}).get("operations", []),
        "projectionSource": proj.get("source"),
        "projectionNote": proj.get("note"),
        "liveMetadata": {
            "available": live is not None,
            "ruleSetVersion": (live or {}).get("ruleSetVersion"),
            "seedVersion": (live or {}).get("seedVersion"),
        },
    }
    return result, "standard"


def tool_metadata_fields(args: dict, tenant: str | None) -> tuple[dict, str]:
    """实体字段：存量字段实时取元数据；增量派生字段单独标注（语义层来源）。"""
    raw = str(args.get("entity") or "").strip()
    if not raw:
        raise ToolError("参数 entity 必填（如 Invoice，或业务术语「发票」）")

    sem = loader.load_semantics()
    live = loader.live_metadata()
    resolved = _resolve_entity(raw, sem)
    if resolved is None:
        known = ", ".join(e.get("entity", "") for e in sem.get("projection", {}).get("entities", []))
        raise ToolError(f"未知实体或术语「{raw}」，投影段已知实体：{known}")

    live_e = ((live or {}).get("entities") or {}).get(resolved) or {}
    derived = [
        dict(df, source="semantic_increment")
        for df in sem.get("increment", {}).get("derived_fields", [])
        if str(df.get("entity", "")).lower() == resolved.lower()
    ]
    result = {
        "entity": resolved,
        "requestedAs": raw if raw != resolved else None,
        "label": live_e.get("label"),
        "fields": live_e.get("fields", []),
        "fieldCount": len(live_e.get("fields", [])),
        "derivedFields": derived,
        "liveMetadata": {
            "available": live is not None,
            "ruleSetVersion": (live or {}).get("ruleSetVersion"),
        },
    }
    if live is None:
        result["note"] = "存量元数据不可达（ERP_AP_BASE），字段清单为空——请检查存量域服务状态"
    return result, "standard"


def tool_metric_get(args: dict, tenant: str | None) -> tuple[dict, str]:
    """派生指标口径：阈值/公式按 租户叠加 -> 行业包 -> Standard 逐层解析，必须给出取值来源取证。"""
    metric = str(args.get("metric") or "").strip()
    if not metric:
        raise ToolError("参数 metric 必填（如 large_risk_amount）")

    sem = loader.load_semantics()
    overlay = loader.load_overlay(tenant)
    partner = loader.load_partner(tenant)
    defs = {m.get("name"): m for m in sem.get("increment", {}).get("metrics", [])}
    if metric not in defs:
        raise ToolError(f"未知指标「{metric}」，可用指标：{', '.join(defs) or '（无）'}")
    m = defs[metric]
    source_layer = "standard"

    if metric == "large_risk_amount":
        param = m.get("parameter")
        ov_param = ((overlay or {}).get("parameters") or {}).get(param) if param else None
        p_param = ((partner or {}).get("parameters") or {}).get(param) if param else None
        if ov_param is not None:
            threshold, source, source_layer = ov_param.get("value"), ov_param.get("source"), "tenant"
        elif p_param is not None:
            threshold, source, source_layer = p_param.get("value"), p_param.get("source"), "partner"
        else:
            threshold, source = m.get("default_threshold"), "Standard 层语义文件默认阈值（无租户/行业叠加）"
        caliber = {"threshold": threshold, "thresholdSource": source,
                   "apply": m.get("apply"), "unit": m.get("unit")}
    elif metric == "net_payable":
        ov_metric = ((overlay or {}).get("metrics") or {}).get(metric)
        p_metric = ((partner or {}).get("metrics") or {}).get(metric)
        if ov_metric is not None:
            formula, note, source_layer = ov_metric.get("formula"), ov_metric.get("note"), "tenant"
        elif p_metric is not None:
            formula, note, source_layer = p_metric.get("formula"), p_metric.get("note"), "partner"
        else:
            formula, note = m.get("caliber_default"), "Standard 层默认口径（无租户/行业叠加）"
        caliber = {"formula": formula, "includesAccrual": "accrual" in str(formula),
                   "note": note}
    else:
        caliber = {"apply": m.get("apply"), "note": "Standard 层定义"}

    result = {
        "metric": metric,
        "description": m.get("description"),
        "caliber": caliber,
        "caliberSource": {"layer": source_layer, "tenantId": tenant,
                          "overlayVersion": (overlay or {}).get("version") if source_layer == "tenant" else None,
                          "partnerId": (partner or {}).get("partner_id") if source_layer == "partner" else None,
                          "partnerVersion": (partner or {}).get("version") if source_layer == "partner" else None},
    }
    return result, source_layer


def tool_term_translate(args: dict, tenant: str | None) -> tuple[dict, str]:
    """业务术语 -> 语义实体。解析顺序：租户叠加 -> 行业包 -> Standard 投影段 -> 反查。"""
    term = str(args.get("term") or "").strip()
    if not term:
        raise ToolError("参数 term 必填（如「进货单」）")

    sem = loader.load_semantics()
    overlay = loader.load_overlay(tenant)
    partner = loader.load_partner(tenant)
    base = {"term": term}

    # 1) 租户 A0 叠加术语（最高优先）
    for t in (overlay or {}).get("terms", []):
        if t.get("business") == term:
            result = dict(base, matched=True, semantic=t.get("semantic"), entity=t.get("semantic"),
                          note=t.get("note"), tenantId=tenant,
                          overlayVersion=(overlay or {}).get("version"))
            return result, "tenant"

    # 2) 行业语义包术语（Partner 层：按租户行业匹配的行业包）
    for t in (partner or {}).get("terms", []):
        if t.get("business") == term:
            result = dict(base, matched=True, semantic=t.get("semantic"), entity=t.get("semantic"),
                          note=t.get("note"), tenantId=tenant,
                          partnerId=(partner or {}).get("partner_id"),
                          partnerVersion=(partner or {}).get("version"))
            return result, "partner"

    # 3) Standard 投影段实体术语
    for e in sem.get("projection", {}).get("entities", []):
        if term in (e.get("terms") or []):
            result = dict(base, matched=True, semantic=e.get("entity"), entity=e.get("entity"),
                          note="Standard 投影段术语（全租户一致）")
            return result, "standard"

    # 4) 反查：语义实体名/别名
    for e in sem.get("projection", {}).get("entities", []):
        if term.lower() == str(e.get("entity", "")).lower():
            result = dict(base, matched=True, semantic=e.get("entity"), entity=e.get("entity"),
                          note="语义实体名直接命中", terms=e.get("terms", []))
            return result, "standard"

    # 5) 未命中：如果租户/行业包定义了该术语，列出各口径（演示「同题不同答」）
    tenant_calibers = _term_in_overlays(term)
    candidates = _term_candidates(term, sem)
    result = dict(base, matched=False, tenantCalibers=tenant_calibers, candidates=candidates,
                  note="Standard 层未定义该术语" +
                       ("；其为租户/行业包口径术语，请携带租户上下文查询" if tenant_calibers else ""))
    return result, "standard"


def tool_task_match(args: dict, tenant: str | None) -> tuple[dict, str]:
    """能力问题清单匹配：精确命中或字符二元组相似度。"""
    question = str(args.get("question") or "").strip()
    if not question:
        raise ToolError("参数 question 必填")

    questions = loader.load_questions()
    scored = sorted(
        ((_similarity(question, q.get("question", "")), q) for q in questions),
        key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0] if scored else (0.0, None)
    if best is None:
        raise ToolError("能力问题清单为空（questions-capability.yaml）")

    matched = best_score >= 0.999 or _norm(question) == _norm(best.get("question", ""))
    alternatives = [
        {"id": q.get("id"), "question": q.get("question"), "intent": q.get("intent"),
         "tools": q.get("tools"), "score": round(s, 3)}
        for s, q in scored[1:4] if s >= 0.2
    ]
    result = {
        "matched": matched,
        "question": {"id": best.get("id"), "question": best.get("question"),
                     "intent": best.get("intent"), "tools": best.get("tools")},
        "score": round(best_score, 3),
        "alternatives": alternatives,
        "note": None if matched else "未达匹配阈值（0.5），请改述或从 alternatives 选择",
    }
    if not matched and best_score >= 0.5:  # 宽松命中仍返回最佳项
        result["matched"] = True
        result["note"] = "模糊命中（相似度 >= 0.5）"
    return result, "standard"


def tool_operation_explain(args: dict, tenant: str | None) -> tuple[dict, str]:
    """BO 操作解释：规格即工具，真源 boapi-spec/bo-ap.yaml 的 x-bo-* 扩展。"""
    op = str(args.get("operation") or "").strip()
    ops = _spec_operations(loader.load_spec())

    if not op:  # 列出全部操作
        return {"operations": [
            {"operation": name, "http": d["http"], "summary": d["summary"],
             "kind": d["kind"], "irreversible": d["irreversible"],
             "sodGroup": d["sod_group"]}
            for name, d in ops.items()]}, "standard"

    if op not in ops:
        raise ToolError(f"未知操作「{op}」，可用操作：{', '.join(ops)}")
    d = ops[op]
    result = {
        "operation": op,
        "http": d["http"],
        "summary": d["summary"],
        "description": d["description"],
        "kind": d["kind"],
        "irreversible": d["irreversible"],
        "approvalPolicy": (
            "强制审批：网关拦截 -> GW.APPROVAL_REQUIRED -> 审批人确认三要素 -> "
            "一次性令牌 OT 重发（参数哈希绑定，120 秒有效）"
            if d["irreversible"] else "无需审批（可逆/只读操作）"),
        "sodGroup": d["sod_group"],
        "idempotency": d["idempotency"],
        "permissions": d["permissions"],
        "completeness": d["completeness"],
        "errorCodes": d["error_codes"],
        "examples": d["examples"],
        "specVersion": (loader.load_spec().get("info", {}).get("version")),
    }
    return result, "standard"


def tool_drift_status(args: dict, tenant: str | None) -> tuple[dict, str]:
    """漂移检测：语义文件增量段 vs 存量元数据现状（预埋漂移必须检出）。"""
    sem = loader.load_semantics()
    live = loader.live_metadata()
    if live is None:
        return {
            "available": False,
            "drifted": None,
            "message": "存量元数据不可达（ERP_AP_BASE 配置或存量域服务状态），无法执行漂移比对",
            "semanticVersion": sem.get("version"),
        }, "standard"
    report = drift_check.check(sem, live)
    report["available"] = True
    return report, "standard"


HANDLERS = {
    "semantic.metadata.entities": tool_metadata_entities,
    "semantic.metadata.fields": tool_metadata_fields,
    "semantic.metric.get": tool_metric_get,
    "semantic.term.translate": tool_term_translate,
    "semantic.task.match": tool_task_match,
    "semantic.operation.explain": tool_operation_explain,
    "semantic.drift.status": tool_drift_status,
}


# ---------------------------------------------------------------- 内部辅助

def _spec_operations(spec: dict) -> dict[str, dict]:
    """遍历 OpenAPI 规格 paths，抽取 operationId -> x-bo-* 扩展（规格即工具）。"""
    ops: dict[str, dict] = {}
    for path, item in (spec.get("paths") or {}).items():
        for method in ("get", "post", "put", "delete", "patch"):
            op_item = item.get(method)
            if not op_item:
                continue
            oid = op_item.get("operationId")
            if not oid:
                continue
            ops[oid] = {
                "summary": op_item.get("summary"),
                "description": (op_item.get("description") or "").strip(),
                "kind": op_item.get("x-bo-operation-kind"),
                "irreversible": bool(op_item.get("x-bo-irreversible")),
                "sod_group": op_item.get("x-bo-sod-group"),
                "idempotency": op_item.get("x-bo-idempotency"),
                "permissions": op_item.get("x-bo-permissions"),
                "completeness": op_item.get("x-bo-completeness"),
                "error_codes": op_item.get("x-bo-error-codes"),
                "examples": op_item.get("x-bo-examples"),
                "http": f"{method.upper()} {path}",
            }
    return ops


def _resolve_entity(raw: str, sem: dict) -> str | None:
    """实体名（大小写不敏感）、业务术语或 live 元数据实体名 -> 投影段/存量实体名。

    口径层术语优先；live 实体名兜底（元数据自动喂养：存量新增实体无需改语义文件即可查询）。
    """
    for e in sem.get("projection", {}).get("entities", []):
        if str(e.get("entity", "")).lower() == raw.lower():
            return e.get("entity")
    for e in sem.get("projection", {}).get("entities", []):
        if raw in (e.get("terms") or []):
            return e.get("entity")
    live = loader.live_metadata()
    for name in ((live or {}).get("entities") or {}):
        if name.lower() == raw.lower():
            return name
    return None


def _term_in_overlays(term: str) -> list[dict]:
    """扫描全部租户叠加与行业包，报告该术语在各层的口径（仅术语字典，不含业务数据）。"""
    import pathlib
    calibers = []
    for path in sorted((loader.BASE_DIR / "overlays").glob("*.yaml")):
        data = loader._read(path).get("overlay", {})
        for t in data.get("terms", []):
            if t.get("business") == term:
                calibers.append({"tenantId": data.get("tenant_id"),
                                 "industry": data.get("industry"),
                                 "semantic": t.get("semantic"), "note": t.get("note")})
    return calibers


def _term_candidates(term: str, sem: dict) -> list[dict]:
    """Standard 术语候选（包含关系，宽松提示）。"""
    key = term.lower()
    out = []
    for e in sem.get("projection", {}).get("entities", []):
        for t in e.get("terms", []):
            if key in str(t).lower() or str(t).lower() in key:
                out.append({"term": t, "semantic": e.get("entity")})
    return out[:5]


def _norm(s: str) -> str:
    return re.sub(r"[？?。，,、\s]", "", str(s)).lower()


def _bigrams(s: str) -> set[str]:
    n = _norm(s)
    return {n[i:i + 2] for i in range(len(n) - 1)} or ({n} if n else set())


def _similarity(a: str, b: str) -> float:
    """字符二元组重叠率（短句改述匹配比 Jaccard 宽容，且确定性可评测）。"""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / min(len(ba), len(bb))
