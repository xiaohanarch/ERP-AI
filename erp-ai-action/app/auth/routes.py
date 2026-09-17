"""认证路由：SSO 登录、OAuth 授权码（WorkBuddy）、令牌交换（T2）。

- POST /gw/auth/sso/login       页面 SSO：校验用户名口令 -> T1（azp=surface-erp-page）
- GET  /gw/oauth/authorize      OAuth 授权码流程：登录表单
- POST /gw/oauth/authorize      表单提交 -> 302 redirect_uri?code=
- POST /gw/oauth/token          授权码换 T1（azp=surface-workbuddy）
- GET  /gw/auth/whoami          T1 自省
- POST /gw/auth/exchange        hub 令牌交换：IN 或后端客户凭据 -> T2（注册表/场景/SoD 拦截链）
"""
from __future__ import annotations

import json
import time
import uuid

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.auth import token_service as ts
from app.config import settings
from app.errors import (agent_not_registered, agent_revoked, gw_json, scene_disabled,
                        sod_conflict, tenant_mismatch, unauthorized,
                        validation_error)
from app.mcp import scenes as scenes_mod
from app.registry import service as registry
from app.security import require_t1, verify_backend_client, verify_token

router = APIRouter()

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>ERP 统一登录</title>
<style>
 body{{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f4f5f7;display:flex;justify-content:center;padding-top:8vh}}
 .card{{background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:32px;width:340px}}
 h2{{margin:0 0 8px;font-size:18px}} p{{color:#666;font-size:13px;margin-top:0}}
 label{{font-size:13px;display:block;margin:12px 0 4px}}
 input{{width:100%;box-sizing:border-box;padding:8px;border:1px solid #d0d3d9;border-radius:6px}}
 button{{margin-top:18px;width:100%;padding:9px;background:#1f5fd6;color:#fff;border:0;border-radius:6px;font-size:14px;cursor:pointer}}
 .err{{color:#c0392b;font-size:13px;margin-top:10px}}
</style></head><body><div class="card">
<h2>{title}</h2><p>{desc}</p>
<form method="post" action="{action}">
<input type="hidden" name="client_id" value="{client_id}"/>
<input type="hidden" name="redirect_uri" value="{redirect_uri}"/>
<input type="hidden" name="state" value="{state}"/>
<label>用户名</label><input name="username" autofocus/>
<label>密码</label><input name="password" type="password"/>
<button type="submit">登 录</button>{err}
</form></div></body></html>"""


def _verify_password(username: str, password: str) -> dict | None:
    """经存量系统校验用户名口令（网关不落用户表，存量域是唯一真源）。"""
    try:
        resp = httpx.post(f"{settings.erp_ap_base}/uiapi/auth/verify",
                          json={"username": username, "password": password},
                          headers={"X-Internal-Secret": settings.internal_secret}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except httpx.HTTPError:
        pass
    return None


@router.post("/gw/auth/sso/login")
def sso_login(body: dict):
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not username or not password:
        return validation_error("username/password 必填")
    user = _verify_password(username, password)
    if user is None:
        return unauthorized("用户名或口令错误")
    token = ts.mint_t1(username, user["tenantId"], ts.SURFACE_ERP,
                       display_name=user.get("displayName"), org=user.get("org"))
    return {"token": token, "tokenType": "Bearer", "user": {
        "sub": user["sub"], "username": username, "displayName": user.get("displayName"),
        "tenantId": user["tenantId"], "org": user.get("org"), "title": user.get("title", "")}}


@router.get("/gw/oauth/authorize", response_class=HTMLResponse)
def oauth_authorize_page(client_id: str, redirect_uri: str, state: str = "", response_type: str = "code"):
    if response_type != "code":
        return HTMLResponse("仅支持 response_type=code", status_code=400)
    row = db.query("SELECT redirect_uris FROM service_clients WHERE client_id = %s AND kind = 'surface'",
                   (client_id,), one=True)
    if row is None or redirect_uri not in json.loads(row["redirect_uris"]):
        return HTMLResponse("client_id 未注册或 redirect_uri 不匹配", status_code=400)
    action = "/gw/oauth/authorize"
    html = _LOGIN_PAGE.format(title="WorkBuddy 授权登录", desc="使用 ERP 账号授权登录 WorkBuddy 助手平台",
                              action=action, client_id=client_id, redirect_uri=redirect_uri,
                              state=state or "", err="")
    return HTMLResponse(html)


@router.post("/gw/oauth/authorize")
def oauth_authorize_submit(client_id: str = Form(...), redirect_uri: str = Form(...),
                           state: str = Form(""), username: str = Form(...), password: str = Form(...)):
    row = db.query("SELECT redirect_uris FROM service_clients WHERE client_id = %s AND kind = 'surface'",
                   (client_id,), one=True)
    if row is None or redirect_uri not in json.loads(row["redirect_uris"]):
        return HTMLResponse("client_id 未注册或 redirect_uri 不匹配", status_code=400)
    user = _verify_password(username, password)
    if user is None:
        html = _LOGIN_PAGE.format(title="WorkBuddy 授权登录", desc="使用 ERP 账号授权登录 WorkBuddy 助手平台",
                                  action="/gw/oauth/authorize", client_id=client_id,
                                  redirect_uri=redirect_uri, state=state,
                                  err='<div class="err">用户名或口令错误</div>')
        return HTMLResponse(html, status_code=401)
    code = uuid.uuid4().hex
    db.execute(
        "INSERT INTO oauth_codes (code, client_id, username, tenant_id, display_name, redirect_uri, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, now() + interval '10 minutes')",
        (code, client_id, username, user["tenantId"], user.get("displayName"), redirect_uri))
    sep = "&" if "?" in redirect_uri else "?"
    target = f"{redirect_uri}{sep}code={code}"
    if state:
        target += f"&state={state}"
    return RedirectResponse(target, status_code=302)


@router.post("/gw/oauth/token")
def oauth_token(grant_type: str = Form(...), code: str = Form(...),
                client_id: str = Form(...), client_secret: str = Form(...)):
    if grant_type != "authorization_code":
        return validation_error("仅支持 authorization_code")
    row = db.query("SELECT client_secret FROM service_clients WHERE client_id = %s AND kind = 'surface'",
                   (client_id,), one=True)
    if row is None or client_secret != row["client_secret"]:
        return unauthorized("client 凭据无效")
    code_row = db.query("SELECT * FROM oauth_codes WHERE code = %s", (code,), one=True)
    if code_row is None or code_row["used"] or code_row["client_id"] != client_id:
        return unauthorized("授权码无效或已使用")
    if code_row["expires_at"].timestamp() < time.time():
        return unauthorized("授权码已过期")
    db.execute("UPDATE oauth_codes SET used = TRUE WHERE code = %s", (code,))
    token = ts.mint_t1(code_row["username"], code_row["tenant_id"], ts.SURFACE_WORKBUDDY,
                       display_name=code_row.get("display_name"))
    return {"access_token": token, "token_type": "Bearer", "expires_in": 12 * 3600}


@router.get("/gw/auth/whoami")
def whoami(request: Request):
    claims = require_t1(request)
    return {"sub": claims["sub"], "tenantId": claims.get("tid"), "azp": claims.get("azp"),
            "displayName": claims.get("name"), "scope": claims.get("scope", [])}


# ---------------------------------------------------------------- 令牌交换（T2）
@router.post("/gw/auth/exchange")
def exchange(request: Request, body: dict):
    """hub -> 网关：换取场景级 T2。拦截链：注册表 -> 吊销 -> 租户 -> 场景 -> scope -> SoD。"""
    agent_id = str(body.get("agentId", "")).strip()
    scene = str(body.get("scene", "")).strip()
    tools = body.get("tools") or []

    # 主体来源 A：网关铸造的 IN 令牌（用户会话链路）
    auth = request.headers.get("Authorization", "")
    username = tenant = None
    if auth.startswith("Bearer "):
        claims = verify_token(auth[7:])
        if claims and claims.get("azp") == "erp-ai-action" and claims.get("aud") == "erp-ai-hub":
            username = claims["sub"][2:] if claims["sub"].startswith("u-") else claims["sub"]
            tenant = claims.get("tid")

    # 主体来源 B：后端客户凭据（无头/事件链路，代表指定用户）
    if username is None:
        client_id = body.get("clientId")
        client_secret = body.get("clientSecret")
        username = body.get("username")
        tenant = body.get("tenantId")
        if not (client_id and client_secret and username and tenant
                and verify_backend_client(client_id, client_secret)):
            return unauthorized("需要 IN 令牌或后端客户凭据（clientId/clientSecret/username/tenantId）")

    if not agent_id or not scene or not isinstance(tools, list) or not tools:
        return validation_error("agentId/scene/tools 必填（tools 非空数组）")

    # 1) 注册表：未注册
    agent = registry.get_agent(agent_id)
    if agent is None:
        return agent_not_registered(agent_id)
    # 2) 吊销即时生效
    if agent["status"] != "ACTIVE":
        return agent_revoked(agent_id)
    # 3) 租户一致
    if agent["tenant_id"] != tenant:
        return tenant_mismatch(f"代理租户({agent['tenant_id']})与用户租户({tenant})不符")
    # 4) 场景存在且启用
    if not scenes_mod.is_enabled(scene):
        return scene_disabled(scene)
    scene_tools = scenes_mod.scene_tools(scene)
    # 5) scope = 请求工具 ∩ 场景工具 ∩ Agent 工具清单
    agent_tools = json.loads(agent["tools"])
    allowed = [t for t in tools if t in scene_tools and t in agent_tools]
    if not allowed:
        return gw_json(403, "GW.SCOPE_EXCEEDED",
                       f"请求工具与（场景 {scene} ∩ Agent 清单）交集为空：{tools}", "gateway_policy")
    # 6) 运行期 SoD 互斥
    conflict = registry.sod_conflict_of(allowed)
    if conflict:
        return sod_conflict(conflict)

    token = ts.mint_t2(username, tenant, agent_id, allowed, scene)
    return {"token": token, "tokenType": "Bearer", "expiresIn": 900, "scope": allowed,
            "agent": agent_id, "scene": scene, "delegationChain": {
                "sub": f"u-{username}", "act": {"sub": f"agent:{agent_id}", "act": {"sub": "erp-ai-hub"}}}}
