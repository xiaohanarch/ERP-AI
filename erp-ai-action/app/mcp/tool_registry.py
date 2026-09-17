"""工具注册表：BO 工具（bo-ap.yaml 规格即工具）+ 语义七工具（语义服务 manifest，运行期拉取）。

复用 scripts/gen_manifest.py 的 build_manifest，保证网关与 Java MCP 清单同源。
"""
from __future__ import annotations

import json
import threading
import time

import httpx
import yaml

from app.config import settings


class ToolRegistry:
    def __init__(self) -> None:
        self.bo_tools: dict[str, dict] = {}
        self.semantic_tools: dict[str, dict] = {}
        self.spec_version: str | None = None
        self.ruleset_version: str | None = None
        self.seed_version: str | None = None
        self.appid: str | None = None
        self._semantics_cached_at = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 加载
    def load(self) -> None:
        import sys
        from pathlib import Path
        scripts_dir = Path(settings.spec_path).resolve().parent.parent / "scripts"
        if str(scripts_dir) not in sys.path and scripts_dir.exists():
            sys.path.insert(0, str(scripts_dir))
        try:
            from gen_manifest import build_manifest  # 复用规格解析（单一真源）
        except ImportError:  # 容器内路径 /app/scripts
            sys.path.insert(0, "/app/scripts")
            from gen_manifest import build_manifest

        with open(settings.spec_path, encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        manifest = build_manifest(spec)
        self.bo_tools = {t["name"]: t for t in manifest["tools"]}
        self.spec_version = manifest["spec_version"]
        self.ruleset_version = manifest["ruleset_version"]
        self.seed_version = manifest["seed_version"]
        self.appid = manifest["appid"]
        self.refresh_semantics(force=True)
        print(f"[tool_registry] BO 工具 {len(self.bo_tools)} 个（spec={self.spec_version} "
              f"ruleset={self.ruleset_version} seed={self.seed_version}）；"
              f"语义工具 {len(self.semantic_tools)} 个", flush=True)

    def refresh_semantics(self, *, force: bool = False) -> None:
        """拉取语义服务 manifest（60s 缓存；不可达时保留内置清单）。"""
        if not force and time.time() - self._semantics_cached_at < 60:
            return
        try:
            resp = httpx.get(f"{settings.semantics_base}/manifest", timeout=5,
                             headers={"X-Internal-Secret": settings.internal_secret})
            if resp.status_code == 200:
                data = resp.json()
                tools = {t["name"]: t for t in data.get("tools", [])}
                if tools:
                    with self._lock:
                        self.semantic_tools = tools
                        self._semantics_cached_at = time.time()
                    return
        except httpx.HTTPError:
            pass
        # 内置兜底清单（与 erp-ai-context 契约一致）
        with self._lock:
            if not self.semantic_tools:
                self.semantic_tools = {t["name"]: t for t in _BUILTIN_SEMANTIC}
            self._semantics_cached_at = time.time()

    # ------------------------------------------------------------ 查询
    def find(self, name: str) -> dict | None:
        if name in self.bo_tools:
            return self.bo_tools[name]
        self.refresh_semantics()
        return self.semantic_tools.get(name)

    def is_semantic(self, name: str) -> bool:
        return name.startswith("semantic.")

    def known_tools(self) -> set[str]:
        self.refresh_semantics()
        return set(self.bo_tools) | set(self.semantic_tools)

    def sod_groups_of(self, tools: list[str]) -> set[str]:
        groups = set()
        for t in tools:
            tool = self.bo_tools.get(t)
            if tool and tool.get("sod_group"):
                groups.add(tool["sod_group"])
        return groups

    def versions(self) -> dict:
        return {"specVersion": self.spec_version, "rulesetVersion": self.ruleset_version,
                "seedVersion": self.seed_version, "boToolCount": len(self.bo_tools),
                "semanticToolCount": len(self.semantic_tools)}

    def mcp_tools(self) -> list[dict]:
        """MCP tools/list 条目（BO + 语义）。"""
        result = []
        for t in self.bo_tools.values():
            result.append({
                "name": t["name"],
                "description": (t["summary"] + "\n" + t["description"]).strip(),
                "inputSchema": t["input_schema"],
            })
        self.refresh_semantics()
        for t in self.semantic_tools.values():
            result.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("input_schema", {"type": "object", "properties": {}}),
            })
        return result


tool_registry = ToolRegistry()

# 语义服务不可达时的内置兜底（正常以 /manifest 拉取为准）
_BUILTIN_SEMANTIC = [
    {"name": "semantic.metadata.entities",
     "description": "查询语义层实体清单（含业务术语映射）",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "semantic.metadata.fields",
     "description": "查询实体字段（含术语与派生指标口径）",
     "input_schema": {"type": "object", "properties": {"entity": {"type": "string"}},
                      "required": ["entity"]}},
    {"name": "semantic.metric.get",
     "description": "获取派生指标定义与租户口径（A0 叠加）",
     "input_schema": {"type": "object", "properties": {"metric": {"type": "string"}},
                      "required": ["metric"]}},
    {"name": "semantic.term.translate",
     "description": "业务术语 <-> 语义术语翻译（如「进货单」-> goods_receipt）",
     "input_schema": {"type": "object", "properties": {"term": {"type": "string"}},
                      "required": ["term"]}},
    {"name": "semantic.task.match",
     "description": "能力问题清单匹配（30 条锚点问题）",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                      "required": ["question"]}},
    {"name": "semantic.operation.explain",
     "description": "解释 BO 操作（规格即工具：性质/权限/幂等/审批要求）",
     "input_schema": {"type": "object", "properties": {"operation": {"type": "string"}},
                      "required": ["operation"]}},
    {"name": "semantic.drift.status",
     "description": "语义层漂移检测状态（增量段 vs 元数据现状）",
     "input_schema": {"type": "object", "properties": {}}},
]
