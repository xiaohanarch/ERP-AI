"""模型网关：全系统唯一的模型调用出口（OpenAI 兼容）。

模式：
  mock   -> 直接调 MODEL_BASE（脚本化确定性应答容器）
  replay -> 录制回放：key = hash(model + scene + messages)；三版本戳（seed/spec/semantics）
            任一变更自动作废；未命中按 REPLAY_MISS_MODE（strict 失败 / passthrough 透传 mock）
  live   -> 真实供应商（OpenAI 兼容：DeepSeek/GLM/Qwen）

每次完成：成本台账入库（租户/代理/场景/用户四维）+ 审计 + OTel chat span（GenAI 字段）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx

from app import audit, cost, otel_setup
from app.config import settings
from app.mcp.tool_registry import tool_registry


class ModelGwError(Exception):
    def __init__(self, code: str, message: str, status: int = 503, retryable: bool = True):
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        super().__init__(message)


class ReplayStore:
    """JSONL 录制库：内存索引 + 文件 mtime 惰性重载。"""

    def __init__(self) -> None:
        self._index: dict[str, dict] = {}
        self._mtime: float | None = None
        self._lock = threading.Lock()

    def _path(self) -> Path:
        p = Path(settings.recordings_dir) / "recordings.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _reload_if_needed(self) -> None:
        path = self._path()
        if not path.exists():
            with self._lock:
                self._index = {}
                self._mtime = None
            return
        mtime = path.stat().st_mtime
        if mtime == self._mtime:
            return
        index: dict[str, dict] = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    index[rec["key"]] = rec
                except (ValueError, KeyError):
                    continue
        with self._lock:
            self._index = index
            self._mtime = mtime

    def get(self, key: str) -> dict | None:
        self._reload_if_needed()
        with self._lock:
            return self._index.get(key)

    def put(self, record: dict) -> None:
        with self._lock:
            self._index[record["key"]] = record
        with open(self._path(), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with self._lock:
            self._mtime = self._path().stat().st_mtime

    def count(self) -> int:
        self._reload_if_needed()
        with self._lock:
            return len(self._index)


replay_store = ReplayStore()
_semantics_version_cache: tuple[float, str] = (0.0, "unknown")


def request_key(model: str, scene: str, messages: list) -> str:
    import hashlib
    from app.security import json_dumps
    raw = f"{model}|{scene}|{json_dumps(messages)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def semantics_version() -> str:
    """语义层版本戳（60s 缓存；不可达时 unknown -> 录制自动作废）。"""
    global _semantics_version_cache
    cached_at, value = _semantics_version_cache
    if time.time() - cached_at < 60:
        return value
    try:
        resp = httpx.get(f"{settings.semantics_base}/versions", timeout=5,
                         headers={"X-Internal-Secret": settings.internal_secret})
        if resp.status_code == 200:
            value = str(resp.json().get("semanticsVersion", "unknown"))
    except httpx.HTTPError:
        value = "unknown"
    _semantics_version_cache = (time.time(), value)
    return value


def version_stamps(model: str) -> dict:
    return {"seed": tool_registry.seed_version, "spec": tool_registry.spec_version,
            "semantics": semantics_version(), "model": model}


# ---------------------------------------------------------------- 主入口
def chat_completion(payload: dict, ctx: dict) -> tuple[dict, str]:
    """返回 (OpenAI 兼容响应, 来源: mock|replay|live)。"""
    model = payload.get("model") or "mock-scene-model"
    scene = payload.get("scene") or ctx.get("scene") or "default"
    messages = payload.get("messages") or []

    mode = settings.model_mode
    source = mode

    if mode == "replay":
        key = request_key(model, scene, messages)
        rec = replay_store.get(key)
        stamps = version_stamps(model)
        if rec is not None and rec.get("versions") == stamps:
            response = rec["response"]
            _after_completion(response, ctx, model, scene)
            return response, "replay"
        if settings.replay_miss_mode == "strict":
            raise ModelGwError("GW.REPLAY_MISS",
                               f"回放未命中且版本戳不匹配（key={key[:12]}...，"
                               f"当前版本 {stamps}）——评测严格模式直接失败", 503)
        # passthrough：演示模式透传 mock
        source = "mock"

    if source == "live":
        response = _call_live(payload)
    else:
        response = _call_mock(payload)

    # 录制（mock/live 模式且开关开启；replay 模式本身不写）
    if settings.model_record and source in ("mock", "live"):
        replay_store.put({
            "key": request_key(model, scene, messages),
            "model": model, "scene": scene,
            "versions": version_stamps(model),
            "request": {"messages": messages},
            "response": response, "ts": time.time(),
        })

    _after_completion(response, ctx, model, scene)
    return response, source


def _call_mock(payload: dict) -> dict:
    resp = httpx.post(f"{settings.model_base}/v1/chat/completions", json=payload, timeout=30)
    if resp.status_code != 200:
        raise ModelGwError("GW.MODEL_UPSTREAM_ERROR",
                           f"mock 模型返回 {resp.status_code}", 502)
    return resp.json()


def _call_live(payload: dict) -> dict:
    if not settings.live_base_url or not settings.live_api_key:
        raise ModelGwError("GW.LIVE_NOT_CONFIGURED",
                           "live 模式未配置 LIVE_BASE_URL/LIVE_API_KEY（可回退 MODEL_MODE=mock）", 501,
                           retryable=False)
    clean = {k: v for k, v in payload.items() if k not in ("scene", "context")}
    clean["model"] = settings.live_model
    resp = httpx.post(f"{settings.live_base_url}/chat/completions", json=clean,
                      headers={"Authorization": f"Bearer {settings.live_api_key}"}, timeout=60)
    if resp.status_code != 200:
        raise ModelGwError("GW.MODEL_UPSTREAM_ERROR",
                           f"供应商({settings.live_provider})返回 {resp.status_code}", 502)
    return resp.json()


def _after_completion(response: dict, ctx: dict, model: str, scene: str) -> None:
    usage = response.get("usage") or {}
    cost.record_usage(tenant_id=ctx.get("tenant"), agent_id=ctx.get("agent"),
                      scene=scene, user_id=ctx.get("user"), model=model,
                      prompt_tokens=usage.get("prompt_tokens", 0),
                      completion_tokens=usage.get("completion_tokens", 0),
                      trace_id=ctx.get("trace"))
    audit.record(tenant_id=ctx.get("tenant"), user_id=ctx.get("user"),
                 agent_id=ctx.get("agent"), azp="erp-ai-hub", action="model_call",
                 outcome="SUCCESS", scene=scene, trace_id=ctx.get("trace"),
                 detail={"model": model, "source": settings.model_mode,
                         "promptTokens": usage.get("prompt_tokens", 0),
                         "completionTokens": usage.get("completion_tokens", 0)})
    attrs = otel_setup.genai_chat_attributes(
        model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
        (response.get("choices") or [{}])[0].get("finish_reason", "stop"))
    attrs.update(otel_setup.identity_attributes(ctx.get("user"), ctx.get("agent"),
                                                "erp-ai-hub", None))
    attrs["scene.code"] = scene
    attrs["scene.tenant"] = ctx.get("tenant")
    with otel_setup.span("chat", attrs):
        pass


def status() -> dict:
    return {"mode": settings.model_mode, "replayMissMode": settings.replay_miss_mode,
            "recording": settings.model_record, "recordings": replay_store.count(),
            "liveProvider": settings.live_provider, "liveModel": settings.live_model,
            "versions": version_stamps(None)}
