"""护栏执行器：入口消息在进入模型/工具前做第一道判定（只加严，不放松）。

判定链分工（纵深防御）：
  1) hub 护栏（本模块）——文本模式拒绝诱导类请求，不入模型不调工具；
  2) 网关 ——T2 scope/SoD/审批拦截（结构化判定，不可绕过）；
  3) 存量域 ——PermissionService 数据权限。
"""
from __future__ import annotations

from hub.assets import resolver


def check(message: str, tenant_id: str | None) -> tuple[bool, dict | None]:
    """返回 (blocked, rule)。blocked=True 时上层必须直接拒绝并给出规则说明。"""
    rules = resolver.guardrail_rules(tenant_id)
    text = message or ""
    for rule in rules:
        if rule.get("action") != "refuse":
            continue
        for pattern in rule.get("patterns") or []:
            if pattern and pattern in text:
                return True, rule
    return False, None
