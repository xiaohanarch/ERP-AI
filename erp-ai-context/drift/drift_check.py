#!/usr/bin/env python3
"""漂移检测：语义文件增量段 vs 存量元数据现状。

预埋漂移（演示口径，必须检出）：
  1) derived_field accrual_flag —— 元数据现状字段名是 is_accrual；
  2) 规则引用 AP.TAX.RATE_CHECK —— 存量规则清单中不存在。

用法（CLI，独立退出码：漂移=1，无漂移=0，上游不可达=2）：
  python drift/drift_check.py [--base http://localhost:8080] [--semantic domains/ap_invoice.yaml]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parent.parent


def load_semantic(path: Path | None = None) -> dict:
    with open(path or REPO / "domains" / "ap_invoice.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["semantics"]


def fetch_live_metadata(base: str) -> dict:
    resp = httpx.get(f"{base.rstrip('/')}/metadata", timeout=10)
    resp.raise_for_status()
    return resp.json()


def check(semantics: dict, live: dict) -> dict:
    """比对增量段引用与元数据现状，返回报告。"""
    drifts: list[dict] = []
    checked = {"fields": 0, "rules": 0}

    live_fields: dict[str, set[str]] = {}
    for entity_name, entity in (live.get("entities") or {}).items():
        live_fields[entity_name.lower()] = {f["name"] for f in entity.get("fields", [])}
    live_rules = {r["ruleId"] for r in (live.get("rules") or [])}

    increment = semantics.get("increment", {})

    # 1) 派生字段：引用的实体必须存在，且若与存量字段同名冲突/引用字段必须存在
    for df in increment.get("derived_fields", []):
        checked["fields"] += 1
        entity_key = str(df.get("entity", "")).lower()
        field_name = df.get("name")
        if entity_key not in live_fields:
            drifts.append({
                "kind": "FIELD_DRIFT", "severity": "HIGH",
                "detail": f"派生字段 {field_name} 引用的实体 {df.get('entity')} 在元数据中不存在",
                "semanticRef": f"{df.get('entity')}.{field_name}", "live": None})
        elif field_name not in live_fields[entity_key]:
            # 同义提示：在实体字段中寻找类型一致的近似字段（如 is_ 前缀）
            similar = sorted(n for n in live_fields[entity_key] if _similar(n, field_name))
            drifts.append({
                "kind": "FIELD_DRIFT", "severity": "HIGH",
                "detail": f"派生字段 {df.get('entity')}.{field_name} 与元数据现状不符"
                          + (f"（疑似对应 {similar[0]}）" if similar else ""),
                "semanticRef": f"{df.get('entity')}.{field_name}",
                "live": similar[0] if similar else None})

    # 2) 规则引用：必须存在于存量规则清单
    for rule_id in increment.get("rules", []):
        checked["rules"] += 1
        if rule_id not in live_rules:
            drifts.append({
                "kind": "RULE_DRIFT", "severity": "MEDIUM",
                "detail": f"语义层引用的规则 {rule_id} 在存量规则清单中不存在（规则已删除或改名）",
                "semanticRef": rule_id, "live": None})

    return {
        "drifted": bool(drifts),
        "counts": {"checkedFields": checked["fields"], "checkedRules": checked["rules"],
                   "drifts": len(drifts)},
        "items": drifts,
        "baseline": {"ruleSetVersion": live.get("ruleSetVersion"),
                     "seedVersion": live.get("seedVersion"),
                     "semanticVersion": semantics.get("version")},
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _similar(a: str, b: str) -> bool:
    """宽松同义判定：is_accrual vs accrual_flag（去前缀/后缀后共享词干）。"""
    stem = lambda s: s.lower().replace("is_", "").replace("_flag", "")  # noqa: E731
    return stem(a) == stem(b) and a != b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("ERP_AP_BASE", "http://localhost:8080"))
    ap.add_argument("--semantic", default=str(REPO / "domains" / "ap_invoice.yaml"))
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()
    try:
        live = fetch_live_metadata(args.base)
    except httpx.HTTPError as e:
        print(f"[drift_check] 元数据不可达（{args.base}）：{e}", file=sys.stderr)
        return 2
    report = check(load_semantic(Path(args.semantic)), live)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "漂移" if report["drifted"] else "一致"
        print(f"[drift_check] {status}：检查字段 {report['counts']['checkedFields']} 个、"
              f"规则 {report['counts']['checkedRules']} 条，漂移 {report['counts']['drifts']} 处")
        for d in report["items"]:
            print(f"  - [{d['kind']}] {d['detail']}")
    return 1 if report["drifted"] else 0


if __name__ == "__main__":
    sys.exit(main())
