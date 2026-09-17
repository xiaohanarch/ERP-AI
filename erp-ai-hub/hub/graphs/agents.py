"""场景图 Agent 选择（租户感知）。

注册表中 Agent 按租户隔离（exchange 强校验 agent.tenant_id == 用户租户，
不符即 GW.TENANT_MISMATCH），场景图按租户映射到对应注册 Agent；
未配置映射的租户（含 T-EAST）使用标品 Agent。
"""
from __future__ import annotations

_AGENTS_BY_TENANT: dict[str, dict[str, str]] = {
    "T-UNI": {"ap-copilot": "uni-copilot", "ap-batch": "uni-batch"},
}


def agent_for(default_agent: str, tenant: str | None) -> str:
    """默认（标品）Agent + 租户 -> 实际注册的 Agent id。"""
    return _AGENTS_BY_TENANT.get(tenant or "", {}).get(default_agent, default_agent)
