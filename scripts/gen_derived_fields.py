#!/usr/bin/env python3
"""从语义层增量段生成派生字段定义（本体驱动结构：本体 -> 生成物 -> BO API）。

产物 legacy-erp-ap/src/main/resources/derived-fields.json 由 Java 通用求值引擎
（DerivedFieldService）加载：本体增量段里带 compute 的派生字段自动成为可查询
的 BO 能力（ap.invoice.getDerivedField），Java 侧不含任何字段特定逻辑。

生成规则：
  - 仅收录带 compute 的派生字段（声明式计算式）；无 compute 的（如 accrual_flag
    引用式映射）留在语义层做漂移比对；
  - 校验：op ∈ {add, subtract}，left/right 基字段必填，name 唯一；
  - 携带语义版本戳（ap-sem-x.y.z）：本体改定义 -> 版本变 -> 产物变 -> API 变。

用法: python scripts/gen_derived_fields.py [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SEMANTIC = REPO / "erp-ai-context" / "domains" / "ap_invoice.yaml"
DEFAULT_OUT = REPO / "legacy-erp-ap" / "src" / "main" / "resources" / "derived-fields.json"

KNOWN_OPS = ("add", "subtract")


def generate(semantic_path: Path) -> dict:
    with open(semantic_path, encoding="utf-8") as f:
        sem = yaml.safe_load(f)["semantics"]

    fields = []
    names: set[str] = set()
    for df in sem.get("increment", {}).get("derived_fields", []):
        compute = df.get("compute")
        if not compute:
            continue  # 引用式映射（无计算式）：留在语义层做漂移比对
        name = str(df.get("name") or "")
        op = str(compute.get("op") or "")
        left, right = compute.get("left"), compute.get("right")
        if not name or op not in KNOWN_OPS or not left or not right:
            raise SystemExit(f"[gen_derived_fields] 非法派生字段定义（name/op/left/right 必填，"
                             f"op ∈ {KNOWN_OPS}）：{df}")
        if name in names:
            raise SystemExit(f"[gen_derived_fields] 派生字段重名：{name}")
        names.add(name)
        fields.append({
            "name": name,
            "entity": df.get("entity"),
            "type": df.get("type"),
            "unit": df.get("unit"),
            "description": df.get("description"),
            "compute": {"op": op, "left": str(left), "right": str(right)},
            "formula": df.get("formula") or f"{left} {op} {right}",
        })
    if not fields:
        raise SystemExit("[gen_derived_fields] 增量段没有可生成的派生字段（带 compute）")
    return {
        "semanticVersion": sem.get("version"),
        "generatedBy": "scripts/gen_derived_fields.py（本体增量段 -> 派生字段定义；生成物，勿手改；"
                       "本体改定义后重跑本脚本并重建 legacy-erp-ap）",
        "derivedFields": fields,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semantic", default=str(SEMANTIC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    doc = generate(Path(args.semantic))
    out = Path(args.out)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[gen_derived_fields] {len(doc['derivedFields'])} 个派生字段（语义版本 "
          f"{doc['semanticVersion']}）-> {out.relative_to(REPO)}")
    for f in doc["derivedFields"]:
        print(f"  - {f['name']} [{f['entity']}] {f['formula']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
