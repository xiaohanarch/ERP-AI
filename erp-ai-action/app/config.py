"""erp-ai-action AI 网关（配置：全部来自环境变量，默认值与 compose/.env.example 对齐）。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Settings:
    # 基础
    database_url: str = _env("DATABASE_URL", "postgresql://erp:erp-demo-pwd@localhost:5432/ai_gw")
    jwt_secret: str = _env("GW_JWT_SECRET", "erp-demo-jwt-secret-0123456789abcdef-0123456789abcdef")
    internal_secret: str = _env("GW_INTERNAL_SECRET", "erp-demo-internal-secret")
    hub_client_secret: str = _env("HUB_CLIENT_SECRET", "erp-demo-hub-client-secret")
    admin_user: str = _env("GW_ADMIN_USER", "admin")
    admin_password: str = _env("GW_ADMIN_PASSWORD", "admin-demo-pwd")

    # 依赖服务
    erp_ap_base: str = _env("ERP_AP_BASE", "http://localhost:8080")
    hub_base: str = _env("HUB_BASE", "http://localhost:8001")
    semantics_base: str = _env("SEMANTICS_BASE", "http://localhost:8002")
    model_base: str = _env("MODEL_BASE", "http://localhost:8090")

    # 模型网关：mock -> replay -> live 三层兜底
    model_mode: str = _env("MODEL_MODE", "mock")  # mock | replay | live
    live_base_url: str = _env("LIVE_BASE_URL")
    live_api_key: str = _env("LIVE_API_KEY")
    live_model: str = _env("LIVE_MODEL", "deepseek-chat")
    live_provider: str = _env("LIVE_PROVIDER", "deepseek")
    replay_miss_mode: str = _env("REPLAY_MISS_MODE", "passthrough")  # strict | passthrough
    model_record: bool = _env("MODEL_RECORD", "false").lower() == "true"
    recordings_dir: str = _env("RECORDINGS_DIR", "/var/lib/gw/recordings")

    # 观测
    jaeger_otlp: str = _env("JAEGER_OTLP", "http://localhost:4318")

    # 规格与场景
    spec_path: str = _env("SPEC_PATH", "/app/boapi-spec/bo-ap.yaml")
    scenes_path: str = _env("SCENES_PATH", "/app/app/scenes.yaml")

    # 审批人（演示环境静态配置：租户 -> 有 ap.approval.decide 权限的用户）
    approvers: dict = field(default_factory=lambda: json.loads(
        _env("GW_APPROVERS_JSON", '{"T-EAST": ["wangwu"], "T-UNI": ["sunba"]}')))

    # SoD 互斥组（演示口径：税码变更与付款执行不得同一主体持有）
    sod_conflicts: tuple = (("ap-tax-write", "ap-payment"),)

    # 审批时效（演示口径）
    approval_pending_ttl_seconds: int = 1800   # PENDING 任务 30 分钟过期
    ot_ttl_seconds: int = 120                  # 一次性令牌 120 秒
    idempotency_ttl_seconds: int = 300         # 网关幂等短窗 5 分钟


settings = Settings()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if not Path(settings.spec_path).exists():
    # 本地（非容器）运行时回退到仓库内路径
    fallback = REPO_ROOT / "boapi-spec" / "bo-ap.yaml"
    if fallback.exists():
        object.__setattr__(settings, "spec_path", str(fallback))
if not Path(settings.scenes_path).exists():
    fallback = Path(__file__).resolve().parent / "scenes.yaml"
    if fallback.exists():
        object.__setattr__(settings, "scenes_path", str(fallback))
