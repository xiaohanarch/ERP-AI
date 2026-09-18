"""Hub API：

  POST /chat/stream          网关 IN 令牌 -> 场景图执行（SSE 事件流）
  POST /internal/resume      审批唤醒（WorkBuddy 审批决定后调用；T1 或内部密钥）
  GET  /internal/resolution  三层资产解析留痕（解析可视化）
  GET  /healthz              健康（检查点库连通性）

SSE 事件协议（网关透传，页面消费）：
  meta / token / tool / approval_required / error / done
"""
from __future__ import annotations

import hmac
import json
import sys
import uuid

import jwt
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from hub import config, db, gw
from hub.assets import guardrails, resolver
from hub.graphs import GRAPHS, USER_SCENES
from hub.graphs.agents import agent_for
from hub.sdk import resume_graph, state_of, stream_graph

router = APIRouter()

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _verify_gw_token(token: str) -> dict | None:
    """验证网关铸造的 JWT（IN：azp=erp-ai-action/aud=erp-ai-hub；T1：azp=surface-*）。

    PyJWT 在令牌含 aud 而未传 audience 参数时会抛 InvalidAudience，
    故关闭框架校验、改为手动判定（IN 要求 aud=erp-ai-hub）。
    """
    try:
        claims = jwt.decode(token, config.settings.jwt_secret, algorithms=["HS256"],
                            issuer="erp-ai-action", options={"verify_aud": False})
    except jwt.PyJWTError:
        return None
    azp = claims.get("azp")
    if azp == "erp-ai-action" and claims.get("aud") == "erp-ai-hub":
        return claims
    if isinstance(azp, str) and azp.startswith("surface-"):
        return claims
    return None


def _caller(request: Request) -> dict | None:
    """鉴权：Bearer IN/T1（网关或页面直调）或内部密钥（脚本/评测）。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        claims = _verify_gw_token(auth[7:])
        if claims:
            sub = claims.get("sub", "")
            return {"user": sub[2:] if sub.startswith("u-") else sub,
                    "tenant": claims.get("tid"), "kind": "token"}
        return None
    secret = request.headers.get("X-Internal-Secret", "")
    if secret and hmac.compare_digest(secret, config.settings.internal_secret):
        return {"user": None, "tenant": None, "kind": "internal"}
    return None


# ---------------------------------------------------------------- 聊天（SSE）
@router.post("/chat/stream")
def chat_stream(request: Request, body: dict):
    caller = _caller(request)
    if caller is None:
        return JSONResponse(status_code=401, content={
            "error": {"code": "HUB.UNAUTHORIZED", "message": "需要网关 IN 令牌或内部密钥"}})
    message = str(body.get("message", "")).strip()
    scene = str(body.get("scene") or "ap.diag")
    conversation_id = str(body.get("conversationId") or f"c-{uuid.uuid4().hex[:12]}")
    user = body.get("user") or caller["user"]
    tenant = body.get("tenant") or caller["tenant"]
    trace = str(body.get("traceId") or f"hub-{uuid.uuid4().hex[:12]}")

    if not message:
        return StreamingResponse(
            iter([_sse({"type": "error", "code": "AP.VALIDATION_ERROR", "message": "消息不能为空"}),
                  _sse({"type": "done"})]),
            media_type="text/event-stream", headers=_SSE_HEADERS)
    if scene not in USER_SCENES:
        return StreamingResponse(
            iter([_sse({"type": "error", "code": "HUB.UNKNOWN_SCENE",
                        "message": f"未知场景：{scene}（可用：{', '.join(USER_SCENES)}）"}),
                  _sse({"type": "done"})]),
            media_type="text/event-stream", headers=_SSE_HEADERS)
    if user is None or tenant is None:
        return StreamingResponse(
            iter([_sse({"type": "error", "code": "HUB.MISSING_IDENTITY",
                        "message": "内部调用必须在请求体携带 user/tenant"})]),
            media_type="text/event-stream", headers=_SSE_HEADERS)

    # 同会话挂起审批未决时拒绝新消息（避免挂起图被新输入覆盖）
    pending = db.wait_by_thread(conversation_id)
    if pending:
        return StreamingResponse(
            iter([_sse({"type": "error", "code": "HUB.APPROVAL_PENDING",
                        "message": f"该会话存在待审批任务 {pending['approvalId']}，"
                                   f"请先完成审批（Approvals 页处理）"}),
                  _sse({"type": "done"})]),
            media_type="text/event-stream", headers=_SSE_HEADERS)

    # 逐请求模型模式钉定（由网关透传；eval/六幕脚本锁 mock，交互面不传走全局默认）
    model_mode = request.headers.get("X-Model-Mode", "")
    if model_mode and model_mode not in ("mock", "replay", "live"):
        return StreamingResponse(
            iter([_sse({"type": "error", "code": "HUB.INVALID_MODEL_MODE",
                        "message": f"X-Model-Mode 必须是 mock/replay/live，收到 {model_mode!r}"}),
                  _sse({"type": "done"})]),
            media_type="text/event-stream", headers=_SSE_HEADERS)

    scene_agents = {"ap.diag": "ap-copilot", "ap.batch": "ap-batch", "ap.taxcode": "ap-copilot"}
    default_agent = scene_agents.get(scene)
    agent = agent_for(default_agent, tenant) if default_agent else None
    return StreamingResponse(
        _run_scene(scene, message, conversation_id, user, tenant, trace, agent, model_mode),
        media_type="text/event-stream", headers=_SSE_HEADERS)


def _run_scene(scene, message, conversation_id, user, tenant, trace, agent, model_mode=""):
    yield _sse({"type": "meta", "conversationId": conversation_id, "scene": scene,
                "agent": agent, "user": user, "tenant": tenant, "traceId": trace})

    # 第一道：hub 护栏（资产文件驱动，只加严）
    blocked, rule = guardrails.check(message, tenant)
    if blocked:
        yield _sse({"type": "error", "code": "HUB.GUARDRAIL_BLOCKED",
                    "message": rule.get("message", "请求被护栏规则拒绝"),
                    "rule": rule.get("id"), "ruleSource": rule.get("source_layer")})
        yield _sse({"type": "done"})
        return

    graph = GRAPHS[scene]()
    state_in = {"message": message, "user": user, "tenant": tenant, "trace": trace,
                "conversation_id": conversation_id, "model_mode": model_mode}
    try:
        for node, delta in stream_graph(graph, state_in, conversation_id):
            if node == "__interrupt__":
                payload = delta or {}
                db.save_wait(payload.get("approvalId"), conversation_id, conversation_id,
                             scene, tenant, user, payload.get("suggestion") or {})
                yield _sse(payload)
                yield _sse({"type": "done"})
                return
            for tc in (delta or {}).get("tool_calls") or []:
                yield _sse({"type": "tool", "tool": tc.get("tool"),
                            "arguments": tc.get("arguments"), "ok": tc.get("ok", True),
                            "error": tc.get("error")})
    except Exception as e:  # noqa: BLE001 —— SSE 协议不允许悬空
        yield _sse({"type": "error", "code": "HUB.INTERNAL_ERROR", "message": str(e)[:200]})
        yield _sse({"type": "done"})
        return

    values = state_of(graph, conversation_id)
    if values.get("error"):
        yield _sse({"type": "error", "code": values["error"].get("code", "HUB.INTERNAL_ERROR"),
                    "message": values["error"].get("message", "")})

    answer = values.get("answer")
    if answer:
        for chunk in _chunks(answer):
            yield _sse({"type": "token", "text": chunk})
    else:
        yield _sse({"type": "token", "text": "（无内容返回）"})

    # 资产解析留痕（三层：本次实际使用的护栏/提示词层与版本）——观测旁路，失败不阻断回答流
    try:
        resolution = _resolution_snapshot(scene, tenant)
        db.log_resolution(conversation_id, scene, tenant, resolution)
    except Exception as e:  # noqa: BLE001 —— SSE 协议不允许悬空
        print(f"[resolution] 解析留痕失败（不影响回答）：{e}", file=sys.stderr)
    yield _sse({"type": "done"})


def _chunks(text: str, size: int = 24):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def _resolution_snapshot(scene: str, tenant: str | None) -> dict:
    guard = resolver.resolve_category("guardrails", tenant)
    prompt, prompt_rec = resolver.system_prompt(scene, tenant)
    return {
        "scene": scene, "tenantId": tenant,
        "guardrails": {"rules": [{"id": r.get("id"), "action": r.get("action"),
                                  "sourceLayer": r.get("source_layer")}
                                 for r in resolver.guardrail_rules(tenant)],
                       "rejectedOverlays": [r for r in guard["record"]
                                            if str(r.get("decision", "")).endswith("rejected")]},
        "prompt": {"resolved": bool(prompt), "assets": prompt_rec["assets"]},
    }


# ---------------------------------------------------------------- 审批唤醒
@router.post("/internal/resume")
def resume(request: Request, body: dict):
    caller = _caller(request)
    if caller is None:
        return JSONResponse(status_code=401, content={
            "error": {"code": "HUB.UNAUTHORIZED", "message": "需要 T1 令牌或内部密钥"}})
    approval_id = str(body.get("approvalId") or "").strip()
    one_time_token = body.get("oneTimeToken")
    if not approval_id:
        return JSONResponse(status_code=400, content={
            "error": {"code": "AP.VALIDATION_ERROR", "message": "approvalId 必填"}})

    wait = db.load_wait(approval_id)
    if wait is None:
        return JSONResponse(status_code=404, content={
            "error": {"code": "HUB.APPROVAL_NOT_FOUND",
                      "message": f"无此审批的挂起会话：{approval_id}"}})
    # 租户校验（T1 调用方必须与审批同租户；内部密钥放行供评测）
    if caller["kind"] == "token" and caller.get("tenant") != wait.get("tenantId"):
        return JSONResponse(status_code=403, content={
            "error": {"code": "GW.TENANT_MISMATCH", "message": "跨租户唤醒被拒绝"}})

    scene = wait.get("scene") or "ap.taxcode"
    if scene not in GRAPHS:
        return JSONResponse(status_code=400, content={
            "error": {"code": "HUB.UNKNOWN_SCENE", "message": f"挂起场景不可恢复：{scene}"}})
    graph = GRAPHS[scene]()
    resume_value = {"oneTimeToken": one_time_token,
                    "rejected": not one_time_token}
    try:
        result = resume_graph(graph, wait["threadId"], resume_value)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={
            "error": {"code": "HUB.INTERNAL_ERROR", "message": str(e)[:200]}})
    db.delete_wait(approval_id)

    answer = result.get("answer", "")
    approval_result = result.get("approval_result", "")
    # 通知原发起人（拒绝/失败也通知）
    gw.push_notification(wait.get("tenantId"), wait.get("userId") or "",
                         kind="approval_decided" if approval_result == "applied" else "info",
                         title=f"税码变更{'已完成' if approval_result == 'applied' else '未执行'}",
                         body=answer[:300])
    return {"ok": True, "approvalId": approval_id, "approvalResult": approval_result,
            "conversationId": wait.get("conversationId"), "answer": answer}


# ---------------------------------------------------------------- 定时调度
@router.post("/internal/scheduler/run")
def scheduler_run(request: Request):
    """手动触发一次定时筛查（演示/验证入口；与后台定时线程同一执行路径，同样留痕）。"""
    if _caller(request) is None:
        return JSONResponse(status_code=401, content={
            "error": {"code": "HUB.UNAUTHORIZED", "message": "需要 T1 令牌或内部密钥"}})
    from hub import scheduler
    return scheduler.run_once(manual=True)


# ---------------------------------------------------------------- 解析可视化
@router.get("/internal/resolution")
def resolution(request: Request, conversation_id: str, tenant: str | None = None):
    caller = _caller(request)
    if caller is None:
        return JSONResponse(status_code=401, content={
            "error": {"code": "HUB.UNAUTHORIZED", "message": "需要 T1 令牌或内部密钥"}})
    items = db.resolutions(conversation_id)
    return {"conversationId": conversation_id, "count": len(items), "items": items}


@router.get("/healthz")
def healthz():
    try:
        from hub.sdk import get_saver
        get_saver()
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "service": "erp-ai-hub", "db": db_ok}
