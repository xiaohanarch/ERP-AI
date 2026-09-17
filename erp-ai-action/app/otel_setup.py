"""OTel：GenAI 风格 span 树（invoke_agent -> chat -> execute_tool）+ 六组扩展字段。

OTLP 不可达时静默降级为 no-op tracer（演示环境不因观测组件缺失而崩溃）。
"""
from __future__ import annotations

import contextlib
from typing import Iterator

from app.config import settings

_provider = None
_tracer = None


def init() -> None:
    """初始化 TracerProvider + OTLP HTTP exporter。失败时降级。"""
    global _provider, _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = Resource.create({
            "service.name": "erp-ai-action",
            "service.namespace": "erp-ai-demo",
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{settings.jaeger_otlp}/v1/traces", timeout=2)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider = provider
        _tracer = trace.get_tracer("erp-ai-action")
        print(f"[otel] OTLP exporter -> {settings.jaeger_otlp}", flush=True)
    except Exception as e:  # noqa: BLE001 —— 观测组件缺失不应阻断服务
        print(f"[otel] 降级为 no-op：{e}", flush=True)


@contextlib.contextmanager
def span(name: str, attributes: dict | None = None) -> Iterator[object]:
    """轻量 span 上下文管理器；未初始化时 no-op。"""
    if _tracer is None:
        yield _NoopSpan()
        return
    with _tracer.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    s.set_attribute(k, v)
        yield s


class _NoopSpan:
    def set_attribute(self, *_args):  # pragma: no cover
        pass

    def record_exception(self, *_args):  # pragma: no cover
        pass


def genai_chat_attributes(model: str, prompt_tokens: int, completion_tokens: int,
                          finish_reasons: str = "stop") -> dict:
    """GenAI 语义约定风格字段（chat span）。"""
    return {
        "genai.request.model": model,
        "genai.usage.input_tokens": prompt_tokens,
        "genai.usage.output_tokens": completion_tokens,
        "genai.response.finish_reasons": finish_reasons,
    }


def identity_attributes(user_id: str | None, agent_id: str | None, azp: str | None,
                        delegation_chain: str | None) -> dict:
    """扩展字段组一：身份（用户/代理/azp/委托链）。"""
    return {
        "enduser.id": user_id,
        "agent.id": agent_id,
        "app.azp": azp,
        "delegation.chain": delegation_chain,
    }


def version_attributes(model: str | None = None) -> dict:
    """扩展字段组二：版本四件套（规格/种子/规则集/模型）。"""
    from app.mcp.tool_registry import tool_registry
    return {
        "version.spec": tool_registry.spec_version,
        "version.seed": tool_registry.seed_version,
        "version.ruleset": tool_registry.ruleset_version,
        "version.model": model,
    }
