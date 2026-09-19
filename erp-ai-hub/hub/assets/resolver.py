"""harness 资产三层解析：Standard -> Partner -> Tenant（确定性顺序）。

规则：
  - 仅 overridable: true 的标品资产可被租户层覆盖；
  - guardrails 类叠加只能加严：租户层只能新增规则或收紧，不能删除/放松标品规则
    （放松类叠加被拒绝并记入解析留痕，供 /internal/resolution 与租检取证）；
  - 每次解析产生解析记录（asset -> 各层版本与决定），供解析可视化。
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import yaml

from hub import config

LAYERS = ["standard", "partner", "tenant"]

# 行业声明缓存（管理端改行业后 ≤10s 生效；语义层不可达回退本地 tenant.yaml）
_INDUSTRY_TTL = 10
_industry_cache: dict[str, tuple[float, str | None]] = {}


class AssetError(ValueError):
    """资产文件不合法（schema 违约）。"""


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    asset = data.get("asset")
    if not isinstance(asset, dict) or not asset.get("name") or not asset.get("category"):
        raise AssetError(f"资产文件缺少 asset.name/category：{path}")
    return asset


def _tenant_dir_name(tenant_id: str) -> str:
    """租户 id -> 资产目录名（T-EAST -> tenant-east，大小写不敏感）。"""
    s = tenant_id.strip()
    if s.upper().startswith("T-"):
        s = s[2:]
    return f"tenant-{s.lower()}"


def _layer_dir(layer: str, tenant_id: str | None) -> Path:
    if layer == "tenant":
        if not tenant_id:
            return Path(config.settings.assets_root) / "_no_tenant_"
        return Path(config.settings.assets_root) / _tenant_dir_name(tenant_id)
    return Path(config.settings.assets_root) / layer


def _tenant_industry(tenant_id: str | None) -> str | None:
    """租户行业声明：<tenant-dir>/tenant.yaml（非资产文件不参与叠加，行业包适配依据）。

    优先语义层配置 API（管理端可改，产品化配置界面写 DB 层；10s 缓存），
    不可达或未配置时回退本地声明文件（标品默认）。
    """
    if not tenant_id:
        return None
    hit = _industry_cache.get(tenant_id)
    if hit and time.time() - hit[0] < _INDUSTRY_TTL:
        return hit[1]
    try:
        resp = httpx.get(f"{config.settings.semantics_base}/internal/config/tenants/{tenant_id}",
                         headers={"X-Internal-Secret": config.settings.internal_secret},
                         timeout=3)
        if resp.status_code == 200:
            industry = ((resp.json().get("config") or {}).get("industry")) or None
            _industry_cache[tenant_id] = (time.time(), industry)
            return industry
    except Exception:  # noqa: BLE001 —— 语义层不可达回退本地文件
        pass
    path = _layer_dir("tenant", tenant_id) / "tenant.yaml"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("industry")


def _assets_in(layer: str, tenant_id: str | None, category: str) -> list[tuple[Path, dict]]:
    root = _layer_dir(layer, tenant_id) / category
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.yaml")):
        out.append((path, _read(path)))
    return out


def resolve_category(category: str, tenant_id: str | None) -> dict:
    """解析某类资产（guardrails/prompts/skills/rules）。返回 {assets, record}。

    record: [{asset, category, layers: [{layer, version}], decision, rejectedOverlays}]
    """
    standard = {a["name"]: a for _, a in _assets_in("standard", None, category)}
    partner = {a["name"]: a for _, a in _assets_in("partner", None, category)}
    tenant = {a["name"]: a for _, a in _assets_in("tenant", tenant_id, category)}

    merged: dict[str, dict] = {}
    record: list[dict] = []

    # Standard 层打底
    for name, asset in standard.items():
        merged[name] = dict(asset, source_layer="standard")
    # Partner 层（行业包）：applies_to.industries 与租户行业声明匹配才生效；
    # 未声明 applies_to 的 Partner 资产全局生效（ISV 通用包语义）
    industry = _tenant_industry(tenant_id)
    for name, asset in partner.items():
        applies = (asset.get("applies_to") or {}).get("industries")
        if applies and (not industry or industry not in applies):
            record.append({"asset": name, "category": category,
                           "decision": "partner_not_applicable",
                           "reason": f"行业包适用行业 {applies}，本租户行业为 {industry or '未声明'}，不加载"})
            continue
        if name in merged and not merged[name].get("overridable"):
            record.append({"asset": name, "category": category,
                           "decision": "partner_overlay_rejected",
                           "reason": "标品资产未标记 overridable"})
            continue
        merged[name] = dict(asset, source_layer="partner")
    # Tenant 层（A0 叠加）
    for name, asset in tenant.items():
        if name not in merged:
            merged[name] = dict(asset, source_layer="tenant")
            continue
        base = merged[name]
        if not base.get("overridable"):
            record.append({"asset": name, "category": category,
                           "decision": "tenant_overlay_rejected",
                           "reason": "标品资产未标记 overridable，租户层不可覆盖"})
            continue
        if category == "guardrails":
            relaxed = _relaxation_of(base, asset)
            if relaxed:
                record.append({"asset": name, "category": category,
                               "decision": "tenant_overlay_rejected",
                               "reason": f"护栏只能加严，检测到放松：{relaxed}"})
                continue
            merged[name] = _strict_merge(base, asset)
        else:
            merged[name] = dict(asset, source_layer="tenant")

    for name, asset in merged.items():
        layers = [{"layer": asset["source_layer"], "version": asset.get("version")}]
        record.append({"asset": name, "category": category, "layers": layers,
                       "decision": "resolved"})
    return {"assets": merged, "record": record}


def _relaxation_of(base: dict, overlay: dict) -> str | None:
    """检测租户护栏叠加是否放松标品规则（删除规则或把 refuse 降为 allow）。"""
    base_rules = {r.get("id"): r for r in base.get("rules", [])}
    overlay_rules = {r.get("id"): r for r in overlay.get("rules", [])}
    for rule_id, rule in base_rules.items():
        if rule.get("action") == "refuse" and rule_id not in overlay_rules \
                and overlay_rules:
            # 标品拒绝规则被移除（叠加文件非空但不含该规则）——仅当 overlay 显式
            # 声明 replaces: true 才视为替换，否则为新增语义
            if overlay.get("replaces"):
                return f"移除标品拒绝规则 {rule_id}"
        if rule_id in overlay_rules and rule.get("action") == "refuse" \
                and overlay_rules[rule_id].get("action") != "refuse":
            return f"规则 {rule_id} 由 refuse 放松为 {overlay_rules[rule_id].get('action')}"
    return None


def _strict_merge(base: dict, overlay: dict) -> dict:
    """护栏加严合并：标品规则全保留，租户规则按 id 合并（refuse 不降级）+ 追加。"""
    rules = {r.get("id"): dict(r) for r in base.get("rules", [])}
    for rule in overlay.get("rules", []):
        rid = rule.get("id")
        if rid in rules and rules[rid].get("action") == "refuse":
            continue  # 拒绝类规则不可被租户放松，保留标品版本
        rules[rid] = dict(rule)
    return dict(base, rules=list(rules.values()), source_layer="tenant",
                version=overlay.get("version"),
                merged_from=[base.get("version"), overlay.get("version")])


def guardrail_rules(tenant_id: str | None) -> list[dict]:
    """当前生效的全部护栏规则（refuse/notify），带来源层标注。"""
    resolved = resolve_category("guardrails", tenant_id)
    rules = []
    for asset in resolved["assets"].values():
        for rule in asset.get("rules", []):
            rules.append(dict(rule, source_layer=asset["source_layer"],
                              asset=asset["name"]))
    return rules


def system_prompt(scene: str, tenant_id: str | None) -> tuple[str, dict]:
    """场景系统提示词（租户可覆盖 overridable 的提示词资产）。返回 (prompt, 解析记录)。"""
    resolved = resolve_category("prompts", tenant_id)
    rec = {"assets": []}
    prompt = ""
    for name, asset in resolved["assets"].items():
        if name == f"{scene}-system" or name == "ap-system":
            prompt = str(asset.get("prompt", ""))
            rec["assets"].append({"asset": name, "layers": [
                {"layer": asset["source_layer"], "version": asset.get("version")}]})
    return prompt, rec
