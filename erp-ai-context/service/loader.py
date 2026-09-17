"""语义资产加载器：语义文件 / 租户叠加 / 能力问题清单 / BO 规格 / 实时元数据（60s 缓存）。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ERP_AP_BASE = os.environ.get("ERP_AP_BASE", "http://localhost:8080")

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, loader):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = loader()
    _cache[key] = (time.time(), value)
    return value


def load_semantics() -> dict:
    return _cached("semantics", 30, lambda: _read(BASE_DIR / "domains" / "ap_invoice.yaml")["semantics"])


def load_questions() -> list[dict]:
    return _cached("questions", 30, lambda: _read(BASE_DIR / "questions-capability.yaml")["questions"])


def load_spec() -> dict:
    """bo-ap.yaml（规格即工具：operation.explain 的真源）。容器内 /app/boapi-spec，仓库布局为兄弟目录。"""
    def _load():
        for path in (BASE_DIR / "boapi-spec" / "bo-ap.yaml",
                     BASE_DIR.parent / "boapi-spec" / "bo-ap.yaml"):
            if path.exists():
                return _read(path)
        raise FileNotFoundError("boapi-spec/bo-ap.yaml 未找到（容器内 /app 或仓库根目录）")
    return _cached("spec", 30, _load)


def load_overlay(tenant_id: str | None) -> dict | None:
    """租户 A0 叠加（不存在则 None —— 全部回退 Standard 层）。"""
    if not tenant_id:
        return None
    overlays_dir = BASE_DIR / "overlays"
    for path in sorted(overlays_dir.glob("*.yaml")):
        data = _read(path).get("overlay", {})
        if data.get("tenant_id") == tenant_id:
            return data
    return None


def live_metadata() -> dict | None:
    """存量元数据现状（投影段实时取数 + 漂移比对基准）。不可达时 None。"""
    def _fetch():
        try:
            resp = httpx.get(f"{ERP_AP_BASE.rstrip('/')}/metadata", timeout=8)
            if resp.status_code == 200:
                return resp.json()
        except httpx.HTTPError:
            pass
        return None
    return _cached("live_metadata", 60, _fetch)


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def semantic_version() -> str:
    return str(load_semantics().get("version", "unknown"))
