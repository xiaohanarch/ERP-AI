"""erp-ai-hub 入口：FastAPI + 事件订阅线程。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hub import events
from hub.api import router

app = FastAPI(title="erp-ai-hub", version="1.0.0",
              description="业务 Hub：LangGraph 场景图 + 审批断点 + 三层资产解析")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8088", "http://localhost:8080", "http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"])

app.include_router(router)


@app.on_event("startup")
def startup():
    # 检查点表初始化（幂等）+ 事件订阅线程
    events.start()
