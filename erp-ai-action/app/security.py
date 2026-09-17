"""请求级安全工具：T1/T2/IN 校验、admin/internal 鉴权（与网关拦截链配套）。"""
from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import Request

from app import db
from app.config import settings
from app.errors import unauthorized


def _constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def verify_token(token: str) -> dict | None:
    """HS256 校验 JWT；失败返回 None。

    leeway=30s：Windows/WSL2 宿主时钟周期性回拨会让刚铸造令牌的 iat 短暂落在
    "未来"（ImmatureSignature），同一令牌数秒后又可通过——演示环境实测偶发 401
    即此因。30 秒宽限是时钟漂移的标准缓解，对令牌安全语义影响可忽略。
    """
    import jwt
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], leeway=30)
    except Exception:  # noqa: BLE001
        return None


def bearer_claims(request: Request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return verify_token(auth[7:])


def require_t1(request: Request) -> dict:
    """页面/WorkBuddy 用户令牌（azp=surface-*）。失败抛 HTTPException(401)。"""
    from fastapi import HTTPException
    claims = bearer_claims(request)
    if claims is None or not str(claims.get("azp", "")).startswith("surface-"):
        raise HTTPException(status_code=401, detail="需要用户令牌（T1）")
    return claims


def is_internal(request: Request) -> bool:
    secret = request.headers.get("X-Internal-Secret", "")
    return bool(secret) and _constant_eq(secret, settings.internal_secret)


def is_admin(request: Request) -> bool:
    """admin = HTTP Basic（GW_ADMIN_*) 或 X-Internal-Secret（脚本/服务间）。"""
    if is_internal(request):
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            raw = base64.b64decode(auth[6:]).decode("utf-8")
            user, _, pwd = raw.partition(":")
        except Exception:  # noqa: BLE001
            return False
        return _constant_eq(user, settings.admin_user) and _constant_eq(pwd, settings.admin_password)
    return False


def verify_backend_client(client_id: str, client_secret: str) -> bool:
    row = db.query("SELECT client_secret FROM service_clients WHERE client_id = %s AND kind = 'backend'",
                   (client_id,), one=True)
    return row is not None and _constant_eq(client_secret, row["client_secret"])


def params_hash(arguments: dict) -> str:
    """审批参数指纹：JSON 规范化后 sha256（键排序，保证确定性）。"""
    canonical = json_dumps(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def json_dumps(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:16]}"
