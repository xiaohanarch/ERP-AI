#!/usr/bin/env python3
"""从 boapi-spec/bo-ap.yaml 生成工具清单 manifest（规格即工具）。

产物 bo-tools-manifest.json 由两处消费：
  - legacy-erp-ap 构建期复制进 classpath，作为 MCP 分发器的工具注册表；
  - 文档/校验参考（网关运行时直接读 YAML，保持单一真源）。

manifest 每个工具携带：
  input_schema —— 由 OpenAPI 参数（path/query/header + requestBody）拉平成 JSON Schema；
  binding      —— 参数名 -> 实际落点（path/query/header/body），供 MCP 分发器回填。

用法: python scripts/gen_manifest.py [--out <path>]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "boapi-spec" / "bo-ap.yaml"

# header 参数名 -> MCP 工具参数名（JSON 参数不宜带连字符）
HEADER_ARG_RENAME = {"Idempotency-Key": "idempotencyKey"}


def resolve_ref(spec: dict, schema: dict) -> dict:
    """就地解析本地 $ref（#/components/schemas/...），仅支持一层引用展开。"""
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/components/schemas/"):
            return schema
        target = spec.get("components", {}).get("schemas", {}).get(ref.rsplit("/", 1)[-1])
        return copy.deepcopy(target) if target else schema
    return schema


def type_of(param_schema: dict) -> str:
    t = param_schema.get("type")
    if isinstance(t, list):
        return "string"
    return t or "string"


def build_tool(spec: dict, path: str, method: str, op: dict) -> dict:
    properties: dict = {}
    required: list[str] = []
    binding: dict = {}

    for p in op.get("parameters", []):
        name = p["name"]
        arg = HEADER_ARG_RENAME.get(name, name)
        schema = p.get("schema", {"type": "string"})
        prop = dict(schema)
        if p.get("description"):
            prop.setdefault("description", p["description"])
        properties[arg] = prop
        if p.get("required"):
            required.append(arg)
        binding[arg] = {"in": p.get("in", "query"), "name": name}

    body = op.get("requestBody")
    if body:
        json_body = body.get("content", {}).get("application/json", {})
        body_schema = resolve_ref(spec, json_body.get("schema", {"type": "object"}))
        for pname, pschema in body_schema.get("properties", {}).items():
            prop = dict(pschema)
            properties[pname] = prop
            binding[pname] = {"in": "body", "name": pname}
        for pname in body_schema.get("required", []):
            required.append(pname)

    return {
        "name": op["operationId"],
        "summary": op.get("summary", ""),
        "description": op.get("description", "").strip(),
        "kind": op.get("x-bo-operation-kind", "read"),
        "irreversible": bool(op.get("x-bo-irreversible", False)),
        "sod_group": op.get("x-bo-sod-group"),
        "permissions": op.get("x-bo-permissions", {}).get("required", []),
        "error_codes": op.get("x-bo-error-codes", []),
        "http": {"method": method.upper(), "path": path},
        "input_schema": {"type": "object", "properties": properties, "required": required},
        "binding": binding,
        "examples": op.get("x-bo-examples", []),
    }


def build_manifest(spec: dict) -> dict:
    meta = spec.get("info", {}).get("x-bo-metadata", {})
    tools = []
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method in ("get", "post", "put", "delete", "patch"):
                tools.append(build_tool(spec, path, method, op))
    return {
        "spec_version": meta.get("spec_version", spec["info"]["version"]),
        "ruleset_version": meta.get("ruleset_version"),
        "seed_version": meta.get("seed_version"),
        "appid": meta.get("appid"),
        "domain": meta.get("domain"),
        "tools": tools,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "legacy-erp-ap" / "src" / "main" / "resources" / "bo-tools-manifest.json"))
    args = ap.parse_args()

    with open(SPEC, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    manifest = build_manifest(spec)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[gen_manifest] {len(manifest['tools'])} tools -> {out}")
    for t in manifest["tools"]:
        print(f"  - {t['name']} [{t['kind']}{'|irreversible' if t['irreversible'] else ''}] args={list(t['input_schema']['properties'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
