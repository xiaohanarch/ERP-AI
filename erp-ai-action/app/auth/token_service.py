"""令牌服务：RFC 8693 风格逐跳令牌交换（T1 -> IN -> T2 -> T3 / OT）。

| 跳 | 令牌 | 关键 claims | 判定 |
|----|------|-------------|------|
| 用户->入口 | T1 | sub=u-*, azp=surface-*, tid, scope=[chat] | 网关验 SSO/OAuth |
| 网关->hub | IN | sub 不变, azp=erp-ai-action, aud=erp-ai-hub | hub 验共享密钥 |
| hub->网关 | T2 | sub 不变, azp=erp-ai-hub, act=完整委托链, scope=场景∩Agent | 网关查注册表 |
| 网关->Java | T3 | azp=erp-ai-action, scope=[单工具], exp 60s | Java 走 PermissionService |
| 审批完成 | OT | jti 一次性, params_hash, exp 120s | 网关验后放行一次写操作 |

逐跳收窄：scope 单调递减，act 链单调增长。
"""
from __future__ import annotations

import time
import uuid

import jwt

from app.config import settings

ALG = "HS256"
SURFACE_ERP = "surface-erp-page"
SURFACE_WORKBUDDY = "surface-workbuddy"


def _mint(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALG)


def _base(sub: str, tenant: str, azp: str, scope: list[str], ttl: int, **extra) -> dict:
    now = int(time.time())
    claims = {"sub": sub, "tid": tenant, "azp": azp, "scope": scope,
              "iat": now, "exp": now + ttl, "iss": "erp-ai-action", "jti": uuid.uuid4().hex[:16]}
    claims.update({k: v for k, v in extra.items() if v is not None})
    return claims


# ---------------------------------------------------------------- T1（用户->入口）
def mint_t1(username: str, tenant: str, azp: str, *, display_name: str | None = None,
            org: str | None = None, ttl: int = 12 * 3600) -> str:
    claims = _base(f"u-{username}", tenant, azp, ["chat"], ttl,
                   name=display_name, org=org)
    return _mint(claims)


# ---------------------------------------------------------------- IN（网关->hub）
def mint_in(username: str, tenant: str, *, display_name: str | None = None,
            org: str | None = None, ttl: int = 900) -> str:
    claims = _base(f"u-{username}", tenant, "erp-ai-action", ["chat"], ttl,
                   aud="erp-ai-hub", name=display_name, org=org)
    return _mint(claims)


# ---------------------------------------------------------------- T2（hub->网关，场景级）
def mint_t2(username: str, tenant: str, agent_id: str, tools: list[str], scene: str,
            ttl: int = 900) -> str:
    act = {"sub": f"agent:{agent_id}", "act": {"sub": "erp-ai-hub"}}
    claims = _base(f"u-{username}", tenant, "erp-ai-hub", tools, ttl,
                   act=act, scene=scene, agent=agent_id)
    return _mint(claims)


# ---------------------------------------------------------------- T3（网关->Java，单工具 60s）
def mint_t3(username: str, tenant: str, agent_id: str, tool: str, scene: str,
            trace_id: str | None, act_chain: dict | None = None, ttl: int = 60) -> str:
    claims = _base(f"u-{username}", tenant, "erp-ai-action", [tool], ttl,
                   act=act_chain or {"sub": f"agent:{agent_id}", "act": {"sub": "erp-ai-hub"}},
                   scene=scene, agent=agent_id, trace_id=trace_id)
    return _mint(claims)


# ---------------------------------------------------------------- OT（一次性审批令牌）
def mint_ot(username: str, approver: str, tenant: str, tool: str, approval_id: str,
            params_hash: str, jti: str, ttl: int | None = None) -> str:
    ttl = ttl if ttl is not None else settings.ot_ttl_seconds
    claims = _base(f"u-{username}", tenant, "erp-ai-action", [tool], ttl,
                   approver=approver, approval_id=approval_id, params_hash=params_hash,
                   ot_type="one_time", jti=jti)
    return _mint(claims)


def verify(token: str) -> dict:
    """严格校验（含 exp/iss）；异常向上抛由调用方决定错误码。"""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALG], issuer="erp-ai-action")
