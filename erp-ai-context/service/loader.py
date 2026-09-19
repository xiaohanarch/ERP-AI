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


def load_file_overlay(tenant_id: str | None) -> dict | None:
    """租户叠加的文件层（标品出厂默认；产品化配置的回退基准）。"""
    if not tenant_id:
        return None
    overlays_dir = BASE_DIR / "overlays"
    for path in sorted(overlays_dir.glob("*.yaml")):
        data = _read(path).get("overlay", {})
        if data.get("tenant_id") == tenant_id:
            return data
    return None


def load_overlay(tenant_id: str | None) -> dict | None:
    """租户 A0 叠加：DB 层（管理端可改，产品化配置）优先，文件层为出厂默认/回退。"""
    if not tenant_id:
        return None
    try:  # 惰性导入：无 DB/psycopg2 环境下文件层照常工作
        from service import config_store
        stored = config_store.get_stored(tenant_id)
        if stored is not None:
            return stored["config"]
    except Exception:  # noqa: BLE001 —— 存储异常回落文件层，不阻断语义工具
        pass
    return load_file_overlay(tenant_id)


def load_partner(tenant_id: str | None) -> dict | None:
    """行业语义包（Partner 层）：按租户叠加声明的 industry 匹配 overlays/partner-*.yaml。

    解析顺序：租户叠加（tenant）-> 行业包（partner）-> Standard 语义文件。
    """
    if not tenant_id:
        return None
    industry = (load_overlay(tenant_id) or {}).get("industry")
    if not industry:
        return None
    for path in sorted((BASE_DIR / "overlays").glob("partner-*.yaml")):
        data = _read(path).get("overlay", {})
        if data.get("industry") == industry:
            return data
    return None


def effective_projection() -> dict:
    """投影段 = 生成基础层 + 人工口径层（元数据自动喂养的落点）。

    - 生成基础层：实体清单/标签/字段数/枚举，取自存量元数据 /metadata（实时）——
      存量新增实体，投影段自动出现，不需要改语义文件；
    - 人工口径层：业务术语（进货单 -> PO 这类元数据推不出的口径）与维度分组，
      来自语义文件的 projection 段（人只写机器推不出来的东西）；
    - 冷启动回退：/metadata 不可达时，用语义文件里的静态实体清单（同 live_metadata 模式）。
    """
    sem = load_semantics()
    curated = sem.get("projection", {}) or {}
    live = live_metadata()
    live_entities = (live or {}).get("entities") or {}
    if not live_entities:
        fallback = {**curated, "source": "fallback"}
        fallback["note"] = "存量元数据不可达：实体清单为语义文件冷启动回退"
        return fallback
    curated_terms: dict[str, list[str]] = {
        str(e.get("entity")): list(e.get("terms") or [])
        for e in curated.get("entities", [])}
    entities = []
    for name, meta in live_entities.items():
        entities.append({
            "entity": name,
            "terms": curated_terms.get(name, []),
            "label": meta.get("label"),
            "fieldCount": len(meta.get("fields", [])),
        })
    live_enums = (live or {}).get("enums") or {}
    return {
        "entities": entities,
        "dimensions": curated.get("dimensions", []),
        "enums": list(live_enums.keys()) if live_enums else curated.get("enums", []),
        "source": "generated",
        "metaVersion": (live or {}).get("ruleSetVersion"),
        "note": "实体清单/枚举由存量元数据生成（自动喂养）；术语与维度为人工口径层",
    }


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
