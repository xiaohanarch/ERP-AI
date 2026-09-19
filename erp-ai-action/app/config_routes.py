"""租户配置管理路由（产品化配置界面的网关代理层）。

鉴权（判定在网关）：
  - 平台管理员（HTTP Basic admin / 内部密钥）：任意租户（实施/运维通道）；
  - 租户配置管理员（T1 且用户在该租户的 CONFIG_ADMINS 清单）：仅本租户。

代理语义层 /internal/config/*（X-Internal-Secret）；每次变更入审计
（config.update / config.reset，含操作者与变更字段）。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request

from app import audit
from app.config import settings
from app.errors import gw_json, unauthorized, validation_error
from app.security import bearer_claims, is_admin


router = APIRouter()


def _authorize(request: Request, tenant_id: str) -> tuple[dict | None, str | None, object | None]:
    """返回 (claims, actor, 错误响应)。平台管理员任意租户；租户管理员仅本租户。"""
    if is_admin(request):
        return None, "platform-admin", None
    claims = bearer_claims(request)
    if claims is not None and str(claims.get("azp", "")).startswith("surface-"):
        sub = str(claims.get("sub", ""))
        username = sub[2:] if sub.startswith("u-") else sub
        tenant = claims.get("tid")
        if username in (settings.config_admins.get(tenant) or []) and tenant == tenant_id:
            return claims, username, None
        return None, None, gw_json(403, "GW.CONFIG_ADMIN_REQUIRED",
                                   f"用户 {username} 不是租户 {tenant_id} 的配置管理员", "gateway_policy")
    return None, None, unauthorized("需要平台管理员（Basic/内部密钥）或租户配置管理员（T1）")


def _proxy(method: str, path: str, json_body: dict | None = None, params: dict | None = None):
    resp = httpx.request(method, f"{settings.semantics_base}{path}",
                         headers={"X-Internal-Secret": settings.internal_secret},
                         json=json_body, params=params, timeout=15)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"error": {"code": "SEMANTIC.UPSTREAM_ERROR",
                                            "message": resp.text[:160]}}


@router.get("/gw/tenants/{tenant_id}/config")
def get_config(tenant_id: str, request: Request):
    _, _, denied = _authorize(request, tenant_id)
    if denied:
        return denied
    code, body = _proxy("GET", f"/internal/config/tenants/{tenant_id}")
    if code != 200:
        return gw_json(code, body.get("error", {}).get("code", "SEMANTIC.UPSTREAM_ERROR"),
                       body.get("error", {}).get("message", ""), "upstream")
    return body


@router.put("/gw/tenants/{tenant_id}/config")
async def put_config(tenant_id: str, request: Request):
    _, actor, denied = _authorize(request, tenant_id)
    if denied:
        return denied
    try:
        body = await request.json()
        patch = body.get("patch")
        if not isinstance(patch, dict) or not patch:
            return validation_error("patch 必填（可含 industry / parameters / terms / metrics）")
    except Exception:  # noqa: BLE001 —— JSON 解析失败
        return validation_error("请求体必须是 JSON 对象")
    code, resp = _proxy("PUT", f"/internal/config/tenants/{tenant_id}",
                        {"actor": actor, "patch": patch})
    audit.record(action="config.update", outcome="SUCCESS" if code == 200 else "ERROR",
                 tenant_id=tenant_id, user_id=actor if actor != "platform-admin" else None,
                 detail={"fields": sorted(patch.keys()), "version": resp.get("version")})
    if code != 200:
        return gw_json(code, resp.get("error", {}).get("code", "SEMANTIC.UPSTREAM_ERROR"),
                       resp.get("error", {}).get("message", ""), "upstream")
    return resp


@router.delete("/gw/tenants/{tenant_id}/config")
def reset_config(tenant_id: str, request: Request):
    _, actor, denied = _authorize(request, tenant_id)
    if denied:
        return denied
    code, resp = _proxy("DELETE", f"/internal/config/tenants/{tenant_id}",
                        params={"actor": actor})
    audit.record(action="config.reset", outcome="SUCCESS" if code == 200 else "ERROR",
                 tenant_id=tenant_id, user_id=actor if actor != "platform-admin" else None)
    if code != 200:
        return gw_json(code, resp.get("error", {}).get("code", "SEMANTIC.UPSTREAM_ERROR"),
                       resp.get("error", {}).get("message", ""), "upstream")
    return resp


@router.get("/gw/tenants/{tenant_id}/config/changes")
def config_changes(tenant_id: str, request: Request):
    _, _, denied = _authorize(request, tenant_id)
    if denied:
        return denied
    code, body = _proxy("GET", f"/internal/config/tenants/{tenant_id}/changes")
    if code != 200:
        return gw_json(code, body.get("error", {}).get("code", "SEMANTIC.UPSTREAM_ERROR"),
                       body.get("error", {}).get("message", ""), "upstream")
    return body
