"""Hub 配置（环境变量，容器内由 compose 注入）。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent        # erp-ai-hub/（容器内为 /app）
REPO_ROOT = BASE_DIR.parent


def _default_assets_root() -> str:
    """资产根：仓库布局（<repo>/harness-assets）或容器布局（/app/harness-assets）。"""
    for cand in (REPO_ROOT / "harness-assets", BASE_DIR / "harness-assets"):
        if cand.is_dir():
            return str(cand)
    return str(REPO_ROOT / "harness-assets")


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


class Settings:
    # 网关与存量域
    gw_base = _env("GW_BASE", "http://localhost:8000")
    erp_ap_base = _env("ERP_AP_BASE", "http://localhost:8080")
    semantics_base = _env("SEMANTICS_BASE", "http://localhost:8002")
    # 后端客户凭据（exchange 换 T2 / 模型网关调用）
    hub_client_id = "erp-ai-hub"
    hub_client_secret = _env("HUB_CLIENT_SECRET", "hub-demo-secret")
    internal_secret = _env("GW_INTERNAL_SECRET", "dev-internal-secret")
    jwt_secret = _env("GW_JWT_SECRET", "dev-jwt-secret")
    # 检查点数据库（LangGraph PostgresSaver + 审批等待映射）
    database_url = _env("DATABASE_URL", "postgresql://erp:erp-demo-pwd@localhost:5432/hub")
    # harness 资产根（三层解析 Standard -> Partner -> Tenant）
    assets_root = _env("HARNESS_ASSETS_ROOT", _default_assets_root())
    # 模型
    model_name = _env("HUB_MODEL_NAME", "mock-scene-model")
    # 定时调度（形态⑤：Scheduler 触发 Agent；间隔秒数）
    scheduler_enabled = _env("SCHEDULER_ENABLED", "1") == "1"
    scheduler_interval = int(_env("SCHEDULER_INTERVAL", "180"))


settings = Settings()
