"""MCP 网关：/gw/mcp（JSON-RPC 2.0）。BO 工具代理到存量域，语义工具代理到语义服务。

tools/call 拦截链（顺序即优先级）：
  1) T2 校验（azp=erp-ai-hub）
  2) Agent 注册表复查（未注册 401 / 吊销即时 401）
  3) 场景降级开关（GW.SCENE_DISABLED）
  4) T2 scope 精确覆盖（GW.SCOPE_EXCEEDED）
  5) 网关幂等短窗（Idempotency-Key，5 分钟 TTL，挡网络重传）
  6) 不可逆动作 -> 审批（无 OT：GW.APPROVAL_REQUIRED；有 OT：校验一次性+params_hash 后放行）
  7) 铸 T3（单工具 60s）-> 存量域 /mcp -> 审计五要素 + OTel execute_tool span

网关层错误直接以 HTTP 状态码 + 统一错误信封返回（非 JSON-RPC 错误信封），
便于 hub 将其作为结构化异常分支处理。
"""
from __future__ import annotations

import json
import re
import time
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app import audit, db, otel_setup
from app.approval import service as approval_svc
from app.auth import token_service as ts
from app.config import settings
from app.errors import (agent_not_registered, agent_revoked, approval_params_mismatch,
                        approval_required, approval_token_expired, gw_json, internal_error,
                        scene_disabled, scope_exceeded, unauthorized, validation_error)
from app.mcp import scenes as scenes_mod
from app.mcp.tool_registry import tool_registry
from app.registry import service as registry
from app.security import params_hash as compute_hash
from app.security import verify_token

router = APIRouter()

PROTOCOL_VERSION = "2024-11-05"
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def _trace_id(request: Request) -> str:
    tp = request.headers.get("traceparent", "")
    if _TRACEPARENT.match(tp):
        return tp.split("-")[1]
    return uuid.uuid4().hex


def _t2_claims(request: Request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    claims = verify_token(auth[7:])
    if claims is None or claims.get("azp") != "erp-ai-hub" or claims.get("ot_type"):
        return None
    return claims


# ---------------------------------------------------------------- JSON-RPC 入口
@router.post("/gw/mcp")
def mcp_entry(request: Request, body: dict):
    method = body.get("method", "")
    msg_id = body.get("id")

    if method.startswith("notifications/"):
        return Response(status_code=202)

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0", "id": msg_id,
            "result": {"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "erp-ai-action-gateway", "version": "1.0.0"}}})

    if method == "tools/list":
        return _tools_list(request, msg_id)

    if method == "tools/call":
        return _tools_call(request, body, msg_id)

    return JSONResponse({"jsonrpc": "2.0", "id": msg_id,
                         "error": {"code": -32601, "message": f"未知方法：{method}"}}, status_code=200)


def _tools_list(request: Request, msg_id) -> JSONResponse:
    claims = _t2_claims(request)
    if claims is None:
        return unauthorized("需要网关铸造的 T2 令牌（azp=erp-ai-hub）")
    tools = tool_registry.mcp_tools()
    return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}})


def _tools_call(request: Request, body: dict, msg_id):
    trace_id = _trace_id(request)
    claims = _t2_claims(request)
    if claims is None:
        return unauthorized("需要网关铸造的 T2 令牌（azp=erp-ai-hub）")

    username = claims["sub"][2:] if claims["sub"].startswith("u-") else claims["sub"]
    tenant = claims.get("tid")
    agent_id = claims.get("agent")
    scene = claims.get("scene")
    act_chain = claims.get("act")

    params = body.get("params") or {}
    tool_name = params.get("name", "")
    arguments = params.get("arguments") or {}
    context = params.get("context") or {}

    # 2) Agent 注册表复查（吊销对既有 T2 即时生效）
    agent = registry.get_agent(agent_id) if agent_id else None
    if agent is None:
        _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, 401, "GW.AGENT_NOT_REGISTERED")
        return agent_not_registered(agent_id)
    if agent["status"] != "ACTIVE":
        _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, 401, "GW.AGENT_REVOKED")
        return agent_revoked(agent_id)

    tool = tool_registry.find(tool_name)
    if tool is None:
        _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, 400, "AP.VALIDATION_ERROR")
        return validation_error(f"未知工具：{tool_name}")

    # 3) 场景降级开关
    if not scenes_mod.is_enabled(scene):
        _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, 403, "GW.SCENE_DISABLED")
        return scene_disabled(scene)

    # 4) T2 scope 精确覆盖
    if tool_name not in (claims.get("scope") or []):
        _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, 403, "GW.SCOPE_EXCEEDED")
        return scope_exceeded(tool_name)

    # 5) 网关幂等短窗
    idem_key = context.get("idempotencyKey")
    if idem_key:
        cached = _idem_get(tenant, agent_id, tool_name, str(idem_key))
        if cached is not None:
            _audit(tool_name, "SUCCESS", claims, username, tenant, agent_id, scene, trace_id, 200,
                   detail={"idempotentReplay": True})
            return JSONResponse(_mark_cached(cached))

    irreversible = bool(tool.get("irreversible"))
    approver = None
    approval_id = None

    # 6) 不可逆动作 -> 审批
    if irreversible:
        ot_raw = context.get("approvalToken")
        if ot_raw:
            ot_claims = verify_token(str(ot_raw))
            if ot_claims is None or ot_claims.get("ot_type") != "one_time":
                _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, 401,
                       "GW.APPROVAL_TOKEN_EXPIRED")
                return approval_token_expired()
            try:
                ot_info = approval_svc.verify_ot(ot_claims, tool=tool_name,
                                                 p_hash=compute_hash(arguments))
            except approval_svc.ApprovalError as e:
                _audit(tool_name, "DENIED", claims, username, tenant, agent_id, scene, trace_id, e.status, e.code)
                return gw_json(e.status, e.code, e.message, e.category)
            approval_svc.consume_ot(ot_claims)
            # OT 代表原始请求人；approver 单独留痕
            username = ot_info["username"]
            approver = ot_info["approver"]
            approval_id = ot_info["approvalId"]
        else:
            task = approval_svc.create_task(
                tool=tool_name, arguments=arguments, tenant_id=tenant, requested_by=username,
                agent_id=agent_id, scene=scene, context=context, trace_id=trace_id)
            _audit(tool_name, "APPROVAL_REQUIRED", claims, username, tenant, agent_id, scene, trace_id, 403,
                   "GW.APPROVAL_REQUIRED", approval_id=task["approvalId"])
            return approval_required(task["approvalId"],
                                     f"不可逆操作 {tool_name} 需要审批（任务 {task['approvalId']}，"
                                     f"{settings.approval_pending_ttl_seconds // 60} 分钟内有效）")

    # 7) 执行：语义工具 -> 语义服务；BO 工具 -> 铸 T3 代理存量域
    # BO 工具在执行时才把幂等键并入参数（存量域 manifest 声明为必填）：
    # params_hash 只覆盖业务参数，幂等键按任务步骤变化不影响审批指纹匹配。
    call_args = arguments
    if idem_key and not tool_registry.is_semantic(tool_name) and "idempotencyKey" not in arguments:
        call_args = {**arguments, "idempotencyKey": str(idem_key)}
    started = time.time()
    try:
        if tool_registry.is_semantic(tool_name):
            result_body, status = _call_semantics(tool_name, arguments, tenant, username)
        else:
            t3 = ts.mint_t3(username, tenant, agent_id, tool_name, scene, trace_id, act_chain=act_chain)
            result_body, status = _call_java_mcp(msg_id, tool_name, call_args, t3, approver, approval_id)
    except httpx.HTTPError as e:
        _audit(tool_name, "ERROR", claims, username, tenant, agent_id, scene, trace_id, 502,
               "GW.UPSTREAM_ERROR", approver=approver, approval_id=approval_id,
               detail={"error": str(e)[:200]})
        return gw_json(502, "GW.UPSTREAM_ERROR", "上游服务不可达（演示环境，详见服务日志）",
                       "retryable_failure", retryable=True, retry_after_seconds=5)

    is_error = status >= 400 or _rpc_is_error(result_body)
    outcome = "ERROR" if is_error else "SUCCESS"
    error_code = _extract_error_code(result_body) if is_error else None
    completeness = _extract_completeness(result_body)

    # 幂等短窗写入（仅成功结果）
    if idem_key and not is_error:
        _idem_put(tenant, agent_id, tool_name, str(idem_key), result_body)

    _audit(tool_name, outcome, claims, username, tenant, agent_id, scene, trace_id, status,
           error_code, approver=approver, approval_id=approval_id,
           detail={"elapsedMs": int((time.time() - started) * 1000)})
    _tool_span(tool_name, tool, username, agent_id, scene, trace_id, outcome, approver,
               approval_id, completeness, act_chain, elapsed_ms=int((time.time() - started) * 1000))

    return JSONResponse(content=result_body, status_code=200 if status < 400 else status)


# ---------------------------------------------------------------- 上游调用
def _call_java_mcp(msg_id, tool_name: str, arguments: dict, t3: str,
                   approver: str | None, approval_id: str | None) -> tuple[dict, int]:
    rpc = {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
           "params": {"name": tool_name, "arguments": arguments}}
    headers = {"Authorization": f"Bearer {t3}", "Content-Type": "application/json"}
    if approver:
        headers["X-BO-Approver"] = f"u-{approver}" if not str(approver).startswith("u-") else approver
    if approval_id:
        headers["X-BO-Approval-Ref"] = approval_id
    resp = httpx.post(f"{settings.erp_ap_base}/mcp", json=rpc, headers=headers, timeout=30)
    try:
        return resp.json(), resp.status_code
    except ValueError:
        return {"error": {"code": "GW.UPSTREAM_ERROR", "message": resp.text[:200]}}, resp.status_code


def _call_semantics(tool_name: str, arguments: dict, tenant: str | None,
                    username: str | None) -> tuple[dict, int]:
    headers = {"X-Internal-Secret": settings.internal_secret, "Content-Type": "application/json",
               "X-Tenant-Id": tenant or "", "X-User": username or ""}
    resp = httpx.post(f"{settings.semantics_base}/tools/{tool_name}", json=arguments,
                      headers=headers, timeout=15)
    if resp.status_code != 200:
        return {"error": {"code": "GW.UPSTREAM_ERROR",
                          "message": f"语义服务返回 {resp.status_code}"}}, 502
    result = resp.json()
    # 包装为 MCP tools/call 结果信封
    envelope = {"jsonrpc": "2.0", "id": None,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                           "isError": False}}
    return envelope, 200


# ---------------------------------------------------------------- 幂等短窗
def _idem_get(tenant, agent_id, tool, key) -> dict | None:
    row = db.query("SELECT response FROM idempotency_cache "
                   "WHERE cache_key = %s AND expires_at > now()",
                   (_idem_key(tenant, agent_id, tool, key),), one=True)
    if row is None:
        return None
    try:
        return json.loads(row["response"])
    except ValueError:
        return None


def _idem_put(tenant, agent_id, tool, key, response: dict) -> None:
    db.execute("DELETE FROM idempotency_cache WHERE expires_at < now()")
    db.execute(
        "INSERT INTO idempotency_cache (cache_key, tenant_id, agent_id, tool, response, expires_at) "
        "VALUES (%s,%s,%s,%s,%s, now() + interval '300 seconds') "
        "ON CONFLICT (cache_key) DO UPDATE SET response = EXCLUDED.response, expires_at = EXCLUDED.expires_at",
        (_idem_key(tenant, agent_id, tool, key), tenant, agent_id, tool,
         json.dumps(response, ensure_ascii=False)))


def _idem_key(tenant, agent_id, tool, key) -> str:
    return f"{tenant}|{agent_id}|{tool}|{key}"


def _mark_cached(rpc_body: dict) -> dict:
    out = dict(rpc_body)
    out["xCached"] = True
    return out


# ---------------------------------------------------------------- 结果解析
def _rpc_is_error(rpc_body: dict) -> bool:
    result = rpc_body.get("result") if isinstance(rpc_body, dict) else None
    if isinstance(result, dict):
        return bool(result.get("isError"))
    return "error" in rpc_body


def _extract_error_code(rpc_body: dict) -> str | None:
    try:
        text = rpc_body["result"]["content"][0]["text"]
        payload = json.loads(text)
        return payload.get("error", {}).get("code") or payload.get("code")
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def _extract_completeness(rpc_body: dict) -> dict | None:
    """提取 completeness（观测扩展字段组：完整性）。"""
    try:
        text = rpc_body["result"]["content"][0]["text"]
        payload = json.loads(text)
        c = payload.get("completeness")
        if isinstance(c, dict):
            return {"full": c.get("full"), "skipped": c.get("skippedRuleGroups")}
    except (KeyError, IndexError, ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------- 审计 + span
def _audit(action, outcome, claims, username, tenant, agent_id, scene, trace_id,
           http_status, error_code=None, **kw):
    audit.record(tenant_id=tenant, user_id=username,
                 agent_id=f"agent:{agent_id}" if agent_id else None,
                 azp=claims.get("azp"), action=action, outcome=outcome,
                 http_status=http_status, error_code=error_code, scene=scene,
                 approval_id=kw.get("approval_id"), approver=kw.get("approver"),
                 delegation_chain=claims.get("act"), trace_id=trace_id, detail=kw.get("detail"))


def _tool_span(tool_name, tool, username, agent_id, scene, trace_id, outcome, approver,
               approval_id, completeness, act_chain, elapsed_ms):
    attrs = {
        "bo.tool": tool_name,
        "bo.kind": tool.get("kind"),
        "bo.irreversible": bool(tool.get("irreversible")),
        "bo.outcome": outcome,
        "bo.elapsed_ms": elapsed_ms,
        "approval.id": approval_id,
        "approval.approver": approver,
        "scene.code": scene,
        "trace_id": trace_id,
    }
    attrs.update(otel_setup.identity_attributes(username, f"agent:{agent_id}" if agent_id else None,
                                                "erp-ai-hub", json.dumps(act_chain, ensure_ascii=False) if act_chain else None))
    attrs.update(otel_setup.version_attributes())
    if completeness:
        attrs["completeness.full"] = completeness.get("full")
        if completeness.get("skipped"):
            attrs["completeness.skipped"] = ",".join(map(str, completeness["skipped"]))
    with otel_setup.span("execute_tool", attrs):
        pass
