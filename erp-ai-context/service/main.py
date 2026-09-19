"""erp-ai-context 语义服务入口。

网关契约（erp-ai-action 调用）：
  GET  /manifest                      -> {tools: [{name, description, input_schema}]}
  GET  /versions                      -> {semanticsVersion, metaVersion, specVersion}
  POST /tools/{name}                  -> {tool, result, _meta}
     请求头：X-Internal-Secret（必需）/ X-Tenant-Id / X-User
     _meta：{semanticVersion, metaVersion, sourceLayer, tenantId}
"""
from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from service import loader, tools

INTERNAL_SECRET = os.environ.get("GW_INTERNAL_SECRET", "dev-internal-secret")

app = FastAPI(title="erp-ai-context", version="1.0.0",
              description="语义层服务：七查询工具 + 漂移检测 + A0 租户叠加")

# 与网关内置兜底清单同构（网关优先以本 /manifest 为准）
MANIFEST = [
    {"name": "semantic.metadata.entities",
     "description": "查询语义层实体清单（含业务术语映射与实时元数据合并）",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "semantic.metadata.fields",
     "description": "查询实体字段（存量字段实时取元数据 + 派生字段口径）",
     "input_schema": {"type": "object", "properties": {"entity": {"type": "string"}},
                      "required": ["entity"]}},
    {"name": "semantic.metric.get",
     "description": "获取派生指标定义与租户口径（A0 叠加，阈值来源取证）",
     "input_schema": {"type": "object", "properties": {"metric": {"type": "string"}},
                      "required": ["metric"]}},
    {"name": "semantic.term.translate",
     "description": "业务术语 <-> 语义术语翻译（如「进货单」随租户解析为 PO/GR）",
     "input_schema": {"type": "object", "properties": {"term": {"type": "string"}},
                      "required": ["term"]}},
    {"name": "semantic.task.match",
     "description": "能力问题清单匹配（30 条锚点问题 -> 意图与工具绑定）",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                      "required": ["question"]}},
    {"name": "semantic.operation.explain",
     "description": "解释 BO 操作（规格即工具：性质/权限/幂等/审批要求）",
     "input_schema": {"type": "object", "properties": {"operation": {"type": "string"}}}},
    {"name": "semantic.drift.status",
     "description": "语义层漂移检测状态（增量段 vs 元数据现状）",
     "input_schema": {"type": "object", "properties": {}}},
]


def _deny() -> JSONResponse:
    return JSONResponse(status_code=401, content={
        "error": {"code": "SEMANTIC.UNAUTHORIZED",
                  "message": "X-Internal-Secret 缺失或不符"}})


def _check(secret: str | None) -> JSONResponse | None:
    if not secret or not hmac.compare_digest(secret, INTERNAL_SECRET):
        return _deny()
    return None


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "erp-ai-context",
            "semanticsVersion": loader.semantic_version()}


@app.get("/manifest")
def manifest(x_internal_secret: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied
    return {"tools": MANIFEST}


@app.get("/versions")
def versions(x_internal_secret: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied
    live = loader.live_metadata()
    return {
        "semanticsVersion": loader.semantic_version(),
        "metaVersion": (live or {}).get("ruleSetVersion"),
        "specVersion": str(loader.load_spec().get("info", {}).get("version", "unknown")),
    }


@app.post("/tools/{name}")
async def call_tool(name: str, request: Request,
                    x_internal_secret: str | None = Header(None),
                    x_tenant_id: str | None = Header(None),
                    x_user: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied

    handler = tools.HANDLERS.get(name)
    if handler is None:
        return JSONResponse(status_code=404, content={
            "error": {"code": "SEMANTIC.TOOL_NOT_FOUND",
                      "message": f"未知语义工具「{name}」，可用：{', '.join(tools.HANDLERS)}"}})

    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("请求体必须是 JSON 对象")
    except ValueError:
        body = {}

    tenant = (x_tenant_id or "").strip() or None
    try:
        result, source_layer = handler(body, tenant)
    except tools.ToolError as e:
        return JSONResponse(status_code=400, content={
            "error": {"code": "SEMANTIC.VALIDATION_ERROR", "message": str(e)}})

    live = loader.live_metadata()
    return {
        "tool": name,
        "result": result,
        "_meta": {
            "semanticVersion": loader.semantic_version(),
            "metaVersion": (live or {}).get("ruleSetVersion"),
            "sourceLayer": source_layer,
            "tenantId": tenant,
            "user": (x_user or "").strip() or None,
        },
    }


# ---------------------------------------------------------------- 租户配置（产品化配置界面后端）
# 管理端（经网关代理，鉴权在网关）：GET 生效配置 / PUT 按字段合并 / DELETE 恢复出厂。
# 文件层 = 标品出厂默认；DB 层 = 管理端当前配置；每次变更记 sem_config_change_log。
@app.on_event("startup")
def _init_config_store():
    from service import config_store
    config_store.init()


@app.get("/internal/config/tenants/{tenant_id}")
def get_tenant_config(tenant_id: str, x_internal_secret: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied
    from service import config_store
    file_overlay = loader.load_file_overlay(tenant_id)
    stored = config_store.get_stored(tenant_id) if config_store.enabled() else None
    if stored is not None:
        return {"tenantId": tenant_id, "source": "db", "version": stored["version"],
                "updatedBy": stored["updatedBy"], "updatedAt": stored["updatedAt"],
                "config": stored["config"], "fileDefault": file_overlay}
    return {"tenantId": tenant_id, "source": "file", "version": None,
            "updatedBy": None, "updatedAt": None,
            "config": file_overlay, "fileDefault": file_overlay}


@app.put("/internal/config/tenants/{tenant_id}")
async def put_tenant_config(tenant_id: str, request: Request,
                            x_internal_secret: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied
    from service import config_store
    if not config_store.enabled():
        return JSONResponse(status_code=503, content={
            "error": {"code": "SEMANTIC.CONFIG_STORE_DISABLED",
                      "message": f"配置存储不可用（{config_store.reason()}），当前为文件层只读"}})
    try:
        body = await request.json()
        patch = body.get("patch")
        actor = str(body.get("actor") or "unknown")
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch 必填（可含 industry / parameters / terms / metrics）")
    except ValueError as e:
        return JSONResponse(status_code=400, content={
            "error": {"code": "SEMANTIC.VALIDATION_ERROR", "message": str(e)}})
    result = config_store.apply_patch(
        tenant_id, patch, actor, loader.load_file_overlay(tenant_id))
    return {"tenantId": tenant_id, "source": "db", "version": result["version"],
            "updatedBy": result["updatedBy"], "config": result["config"],
            "fileDefault": loader.load_file_overlay(tenant_id)}


@app.delete("/internal/config/tenants/{tenant_id}")
def reset_tenant_config(tenant_id: str, request: Request,
                        actor: str = "unknown",
                        x_internal_secret: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied
    from service import config_store
    if not config_store.enabled():
        return JSONResponse(status_code=503, content={
            "error": {"code": "SEMANTIC.CONFIG_STORE_DISABLED",
                      "message": f"配置存储不可用（{config_store.reason()}）"}})
    config_store.reset(tenant_id, actor)
    return {"tenantId": tenant_id, "source": "file", "reset": True,
            "config": loader.load_file_overlay(tenant_id)}


@app.get("/internal/config/tenants/{tenant_id}/changes")
def tenant_config_changes(tenant_id: str, x_internal_secret: str | None = Header(None)):
    denied = _check(x_internal_secret)
    if denied:
        return denied
    from service import config_store
    return {"tenantId": tenant_id, "changes": config_store.changes(tenant_id)}
