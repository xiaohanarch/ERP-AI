"""erp-ai-action：AI 网关（FastAPI）。启动装配：DB + 工具注册表 + 场景 + OTel + 路由。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, otel_setup
from app.approval import routes as approval_routes
from app.audit import routes as audit_routes
from app.auth import routes as auth_routes
from app.chat import router as chat_router
from app.cost import routes as cost_routes
from app.mcp import scenes as scenes_mod
from app.mcp.gateway import router as mcp_router
from app.mcp.tool_registry import tool_registry
from app.modelgw import routes as modelgw_routes
from app.platform_routes import router as platform_router
from app.registry import routes as registry_routes
from app.subscriptions import routes as subscription_routes

app = FastAPI(title="erp-ai-action AI 网关", version="1.0.0",
              description="Agent 注册中心 / 逐跳令牌交换 / MCP 代理与拦截链 / 审批 / 模型网关 / 审计与成本")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8088", "http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(registry_routes.router)
app.include_router(mcp_router)
app.include_router(approval_routes.router)
app.include_router(audit_routes.router)
app.include_router(cost_routes.router)
app.include_router(modelgw_routes.router)
app.include_router(chat_router)
app.include_router(platform_router)
app.include_router(subscription_routes.router)


@app.on_event("startup")
def startup() -> None:
    db.init()
    tool_registry.load()
    scenes_mod.load()
    otel_setup.init()
    print("[erp-ai-action] 启动完成：路由 /gw/* /v1/chat/completions /internal/*", flush=True)
