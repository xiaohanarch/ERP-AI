"""网关客户端：令牌交换（T2）/ MCP 工具调用 / 模型调用 / 内部通知。

hub 对网关的全部出口集中在此；graph 节点不直接发 HTTP。
"""
from __future__ import annotations

import json

import httpx

from hub.config import settings


class GwError(Exception):
    """网关拒绝（交换失败/网络失败）。code 供 SSE error 事件透出。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class GwToolError(Exception):
    """工具调用被拒或业务失败（网关策略错误信封 / MCP isError）。"""

    def __init__(self, code: str, message: str, remediation: dict | None = None):
        self.code = code
        self.message = message
        self.remediation = remediation or {}
        super().__init__(f"{code}: {message}")


# ---------------------------------------------------------------- 令牌交换
def exchange(agent_id: str, scene: str, tools: list[str], username: str,
             tenant: str | None) -> str:
    """后端客户凭据换 T2（拦截链在网关：注册表/吊销/租户/场景/scope/SoD）。"""
    resp = httpx.post(
        f"{settings.gw_base}/gw/auth/exchange",
        json={"agentId": agent_id, "scene": scene, "tools": tools,
              "clientId": settings.hub_client_id, "clientSecret": settings.hub_client_secret,
              "username": username, "tenantId": tenant},
        timeout=15)
    if resp.status_code != 200:
        err = {}
        try:
            err = (resp.json() or {}).get("error", {})
        except ValueError:
            pass
        raise GwError(err.get("code", "GW.UPSTREAM_ERROR"),
                      err.get("message", f"网关交换失败：HTTP {resp.status_code}"))
    return resp.json()["token"]


# ---------------------------------------------------------------- MCP 工具调用
def mcp_call(t2: str, tool: str, arguments: dict, context: dict | None = None) -> dict:
    """经网关的 tools/call。成功返回工具结果 JSON；失败抛 GwToolError。

    context 携带：idempotencyKey（幂等短窗）/ rationale+impact+snapshot（审批三要素）/
    approvalToken（审批通过后的一次性令牌）。
    """
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments, "context": context or {}}}
    resp = httpx.post(f"{settings.gw_base}/gw/mcp", json=payload,
                      headers={"Authorization": f"Bearer {t2}"}, timeout=60)
    if resp.status_code != 200:
        err = {}
        try:
            err = (resp.json() or {}).get("error", {})
        except ValueError:
            pass
        raise GwToolError(err.get("code", "GW.UPSTREAM_ERROR"),
                          err.get("message", f"网关返回 {resp.status_code}"),
                          err.get("remediation"))
    body = resp.json()
    result = body.get("result") or {}
    text = _first_text(result)
    if result.get("isError"):
        try:
            err = json.loads(text).get("error", {})
        except ValueError:
            err = {"code": "AP.UPSTREAM_ERROR", "message": text[:200]}
        raise GwToolError(err.get("code", "AP.UPSTREAM_ERROR"),
                          err.get("message", text[:200]), err.get("remediation"))
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"raw": text}


def _first_text(result: dict) -> str:
    for item in result.get("content") or []:
        if item.get("type") == "text":
            return str(item.get("text", ""))
    return ""


# ---------------------------------------------------------------- 模型调用
def ask_model(scene: str, messages: list[dict], ctx: dict) -> dict:
    """经网关模型网关的 OpenAI 兼容调用。返回解析后的「下一步动作 JSON」（mock 契约）。"""
    headers = {"X-Client-Id": settings.hub_client_id,
               "X-Client-Secret": settings.hub_client_secret,
               "X-GW-User": ctx.get("user") or "erp-ai-hub",
               "X-GW-Tenant": ctx.get("tenant") or "",
               "X-GW-Agent": ctx.get("agent") or "",
               "X-GW-Trace": ctx.get("trace") or ""}
    resp = httpx.post(f"{settings.gw_base}/v1/chat/completions",
                      json={"model": settings.model_name, "scene": scene,
                            "messages": messages, "stream": False},
                      headers=headers, timeout=60)
    if resp.status_code != 200:
        err = {}
        try:
            err = (resp.json() or {}).get("error", {})
        except ValueError:
            pass
        raise GwError(err.get("code", "GW.MODEL_UPSTREAM_ERROR"),
                      err.get("message", f"模型网关返回 {resp.status_code}"))
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except ValueError:
        return {"intent": "clarify", "reply": content}


# ---------------------------------------------------------------- 内部通知
def push_notification(tenant_id: str | None, username: str, *, kind: str = "info",
                       title: str = "", body: str = "", invoice_no: str = "",
                       summary: str = "") -> None:
    """经网关内部通知入口推送（事件无头诊断结果 / 审批结果）。"""
    try:
        httpx.post(f"{settings.gw_base}/internal/notifications",
                   headers={"X-Internal-Secret": settings.internal_secret},
                   json={"tenantId": tenant_id, "username": username, "kind": kind,
                         "title": title, "body": body, "invoiceNo": invoice_no,
                         "summary": summary},
                   timeout=10)
    except httpx.HTTPError:
        pass  # 通知失败不阻断主流程
