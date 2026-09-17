"""scripts 共享客户端：登录 / 聊天（SSE）/ 令牌交换 / MCP 调用 / 审批 / UI 与 Open API。

被以下脚本复用：tenant_checks / selfcheck / gen_report / headless_mcp / demo/scene_*。
契约与 hub/gw.py、eval/runner/run_eval.py 保持同源（网关错误信封 + MCP 文本负载）。

环境变量可覆盖端点与密钥（默认与 compose 一致）：
  ERP_DEMO_GW / ERP_DEMO_HUB / ERP_DEMO_JAVA / ERP_DEMO_SEM
  ERP_DEMO_INTERNAL_SECRET / ERP_DEMO_HUB_CLIENT_SECRET / ERP_DEMO_PASSWORD
"""
from __future__ import annotations

import json
import os
import time
import uuid

import httpx

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GW = os.environ.get("ERP_DEMO_GW", "http://127.0.0.1:8000")
HUB = os.environ.get("ERP_DEMO_HUB", "http://127.0.0.1:8001")
SEM = os.environ.get("ERP_DEMO_SEM", "http://127.0.0.1:8002")
JAVA = os.environ.get("ERP_DEMO_JAVA", "http://127.0.0.1:8080")

INTERNAL_SECRET = os.environ.get("ERP_DEMO_INTERNAL_SECRET", "erp-demo-internal-secret")
HUB_CLIENT_SECRET = os.environ.get("ERP_DEMO_HUB_CLIENT_SECRET", "erp-demo-hub-client-secret")
HUB_CLIENT_ID = "erp-ai-hub"
DEFAULT_PASSWORD = os.environ.get("ERP_DEMO_PASSWORD", "demo123")

# Open API 事故端点凭据（与 PermissionParityTest 同源）
OPENAPI_CREDS = {
    "T-EAST": ("open-erp-east", "open-east-secret"),
    "T-UNI": ("open-erp-uni", "open-uni-secret"),
}

# 场景 -> 默认 Agent（与 hub/api.py scene_agents 一致）
SCENE_AGENTS = {"ap.diag": "ap-copilot", "ap.batch": "ap-batch", "ap.taxcode": "ap-copilot"}


class GwError(Exception):
    """网关拒绝（交换失败等）。code 供断言。"""

    def __init__(self, code: str, message: str, status: int | None = None):
        self.code, self.message, self.status = code, message, status
        super().__init__(f"{code}: {message}")


class GwToolError(Exception):
    """工具调用被拒或业务失败（网关策略错误信封 / MCP isError）。"""

    def __init__(self, code: str, message: str, remediation: dict | None = None):
        self.code, self.message, self.remediation = code, message, remediation or {}
        super().__init__(f"{code}: {message}")


# ---------------------------------------------------------------- 基础
def run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def new_cid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def fmt_money(n) -> str:
    return f"{int(n):,}"


def unwrap(payload: dict) -> dict:
    """语义工具返回 {tool, result, _meta} 信封；BO 工具直接返回业务负载。"""
    if "tool" in payload and "result" in payload and isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload


def _err_of(resp: httpx.Response) -> dict:
    try:
        return (resp.json() or {}).get("error", {})
    except ValueError:
        return {"code": f"HTTP {resp.status_code}", "message": resp.text[:200]}


# ---------------------------------------------------------------- 登录 / 聊天
_tokens: dict[str, str] = {}


def login(username: str, password: str | None = None) -> str:
    """SSO 登录 -> T1（缓存；与页面同一路径）。"""
    if username in _tokens:
        return _tokens[username]
    resp = httpx.post(f"{GW}/gw/auth/sso/login",
                      json={"username": username, "password": password or DEFAULT_PASSWORD},
                      timeout=15)
    if resp.status_code != 200:
        raise GwError(_err_of(resp).get("code", "GW.LOGIN_FAILED"),
                      _err_of(resp).get("message", f"登录失败 HTTP {resp.status_code}"))
    token = resp.json()["token"]
    _tokens[username] = token
    return token


def logout(username: str) -> None:
    """使登录缓存失效（演示吊销/状态切换后重登）。"""
    _tokens.pop(username, None)


def chat(username: str, scene: str, message: str, conversation_id: str | None = None,
         timeout: float = 120.0) -> dict:
    """hub 聊天（T1 直调，SSE 解析）。

    返回：{conversationId, traceId, answer, tools[], error, approval, done}
      tools[]  = [{tool, arguments, ok, error}]
      error    = 首个 error 事件（护栏拒绝 / 业务错误码）
      approval = approval_required 载荷（三要素）
    """
    token = login(username)
    cid = conversation_id or new_cid(f"sc-{username}")
    out = {"conversationId": cid, "traceId": None, "scene": scene, "user": username,
           "tenant": None, "answer": "", "tools": [], "error": None,
           "approval": None, "done": False}
    body = {"message": message, "scene": scene, "conversationId": cid,
            "traceId": f"script-{uuid.uuid4().hex[:12]}"}
    with httpx.stream("POST", f"{HUB}/chat/stream", json=body, timeout=timeout,
                      headers={"Authorization": f"Bearer {token}"}) as resp:
        if resp.status_code != 200:
            resp.read()
            out["error"] = _err_of(resp)
            return out
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except ValueError:
                continue
            et = ev.get("type")
            if et == "meta":
                out["conversationId"] = ev.get("conversationId", cid)
                out["traceId"] = ev.get("traceId")
                out["tenant"] = ev.get("tenant")
            elif et == "token":
                out["answer"] += ev.get("text", "")
            elif et == "tool":
                out["tools"].append({"tool": ev.get("tool"), "arguments": ev.get("arguments"),
                                     "ok": ev.get("ok", True), "error": ev.get("error")})
            elif et == "error" and out["error"] is None:
                out["error"] = {"code": ev.get("code"), "message": ev.get("message"),
                                "rule": ev.get("rule"), "ruleSource": ev.get("ruleSource")}
            elif et == "approval_required":
                out["approval"] = ev
            elif et == "done":
                out["done"] = True
                break
    return out


# ---------------------------------------------------------------- 令牌交换 / MCP（形态③ 无头链路）
def exchange(agent_id: str, scene: str, tools: list[str], username: str,
             tenant: str) -> str:
    """后端客户凭据换 T2（与 hub/gw.exchange 同款；拦截链在网关）。"""
    resp = httpx.post(
        f"{GW}/gw/auth/exchange",
        json={"agentId": agent_id, "scene": scene, "tools": tools,
              "clientId": HUB_CLIENT_ID, "clientSecret": HUB_CLIENT_SECRET,
              "username": username, "tenantId": tenant},
        timeout=15)
    if resp.status_code != 200:
        err = _err_of(resp)
        raise GwError(err.get("code", "GW.UPSTREAM_ERROR"),
                      err.get("message", f"网关交换失败：HTTP {resp.status_code}"), resp.status_code)
    return resp.json()["token"]


def mcp_call(t2: str, tool: str, arguments: dict, context: dict | None = None,
             msg_id: int = 1) -> dict:
    """经网关的 tools/call。成功返回工具结果 JSON；失败抛 GwToolError。"""
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments, "context": context or {}}}
    resp = httpx.post(f"{GW}/gw/mcp", json=payload,
                      headers={"Authorization": f"Bearer {t2}"}, timeout=60)
    if resp.status_code != 200:
        err = _err_of(resp)
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


def mcp_list(t2: str) -> list[dict]:
    """tools/list（T2 场景内可见工具清单）。"""
    resp = httpx.post(f"{GW}/gw/mcp",
                      json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                      headers={"Authorization": f"Bearer {t2}"}, timeout=15)
    if resp.status_code != 200:
        err = _err_of(resp)
        raise GwToolError(err.get("code", "GW.UPSTREAM_ERROR"), err.get("message", ""))
    return (resp.json().get("result") or {}).get("tools", [])


def _first_text(result: dict) -> str:
    for item in result.get("content") or []:
        if item.get("type") == "text":
            return str(item.get("text", ""))
    return ""


# ---------------------------------------------------------------- 审批闭环
def decide(approval_id: str, approver: str, action: str, comment: str | None = None) -> dict:
    """审批决定（T1 = 审批人；批准返回 oneTimeToken）。"""
    token = login(approver)
    body = {"action": action}
    if comment:
        body["comment"] = comment
    resp = httpx.post(f"{GW}/gw/approvals/{approval_id}/decision", json=body,
                      headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if resp.status_code != 200:
        err = _err_of(resp)
        raise GwToolError(err.get("code", f"HTTP {resp.status_code}"), err.get("message", ""))
    return resp.json()


def resume(approval_id: str, one_time_token: str | None) -> dict:
    """hub 审批唤醒（内部密钥；返回 approvalResult + answer）。"""
    resp = httpx.post(f"{HUB}/internal/resume",
                      headers={"X-Internal-Secret": INTERNAL_SECRET},
                      json={"approvalId": approval_id, "oneTimeToken": one_time_token},
                      timeout=90)
    if resp.status_code != 200:
        err = _err_of(resp)
        raise GwToolError(err.get("code", f"HTTP {resp.status_code}"), err.get("message", ""))
    return resp.json()


def approval_detail(approval_id: str, viewer: str) -> dict:
    """审批任务详情（三要素 + snapshot；跨租户访问会被拒）。"""
    token = login(viewer)
    resp = httpx.get(f"{GW}/gw/approvals/{approval_id}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if resp.status_code != 200:
        err = _err_of(resp)
        raise GwToolError(err.get("code", f"HTTP {resp.status_code}"), err.get("message", ""))
    return resp.json()


# ---------------------------------------------------------------- 存量域三口径
def ui_invoices(username: str) -> dict:
    """页面口径：会话登录 -> UI API（组织数据权限过滤）。"""
    token = login(username)
    with httpx.Client() as client:
        resp = client.post(f"{JAVA}/uiapi/auth/session-login", json={"token": token}, timeout=15)
        if resp.status_code != 200:
            raise GwError("HTTP_SESSION_LOGIN", f"session-login 返回 {resp.status_code}")
        resp2 = client.get(f"{JAVA}/uiapi/invoices", timeout=30)
        resp2.raise_for_status()
        return resp2.json()


def openapi_invoices(tenant: str = "T-EAST", limit: int = 10000) -> dict:
    """Open API 口径：appid 直连（租户级、无组织过滤 —— 事故端点）。"""
    app_id, secret = OPENAPI_CREDS[tenant]
    resp = httpx.get(f"{JAVA}/openapi/invoices", params={"limit": limit},
                     headers={"X-App-Id": app_id, "X-App-Secret": secret}, timeout=120)
    resp.raise_for_status()
    return resp.json()


def bulk_seed(tenant: str = "T-EAST", count: int = 5000) -> dict:
    """bulk 种子（幂等：已有则跳过）。"""
    app_id, secret = OPENAPI_CREDS[tenant]
    resp = httpx.post(f"{JAVA}/openapi/admin/bulk-seed", params={"count": count},
                      headers={"X-App-Id": app_id, "X-App-Secret": secret}, timeout=300)
    resp.raise_for_status()
    return resp.json()


def three_calibers(user: str = "zhangsan", tenant: str = "T-EAST") -> dict:
    """事故三口径取证：页面（组织过滤）vs Open API（租户级）vs BO API（与页面同权限 + 披露）。"""
    ui = ui_invoices(user)
    openapi = openapi_invoices(tenant)
    t2 = exchange("ap-headless", "ap.batch", ["ap.invoice.listBlocked"], user, tenant)
    bo = mcp_call(t2, "ap.invoice.listBlocked", {"pageSize": 100})
    return {
        "user": user, "tenant": tenant,
        "uiTotal": ui.get("total", 0),
        "openapiTotal": openapi.get("total", 0),
        "bo": {
            "total": bo["pageInfo"]["total"],
            "items": [i["invoiceNo"] for i in bo["items"]],
            "orgs": sorted({i["org"] for i in bo["items"]}),
            "filteredByDimension": bo.get("filteredByDimension"),
        },
    }


def caliber_checks(c: dict) -> list[tuple[str, bool, str]]:
    """三口径断言：页面 50 余条 / Open API 5000+（~100 倍事故）/ BO 同权限 + 披露。"""
    bo = c["bo"]
    dims = (bo.get("filteredByDimension") or {}).get("dimensions") or []
    ratio = c["openapiTotal"] / c["uiTotal"] if c["uiTotal"] else 0
    return [
        ("页面口径约 50 条（会话 + 组织过滤）", 50 <= c["uiTotal"] <= 60, f"实际 {c['uiTotal']}"),
        ("Open API 口径 ≥5050 条（租户级事故端点）", c["openapiTotal"] >= 5050, f"实际 {c['openapiTotal']}"),
        ("事故放大倍数 ~100 倍", ratio >= 90, f"{c['uiTotal']} -> {c['openapiTotal']}（×{ratio:.0f}）"),
        ("BO API 与页面同组织口径（仅 ORG-EAST-PROC）", bo["orgs"] == ["ORG-EAST-PROC"], str(bo["orgs"])),
        ("BO API 命中数不超过页面口径", bo["total"] <= c["uiTotal"], f"{bo['total']} ≤ {c['uiTotal']}"),
        ("BO API 披露过滤维度（含 org）", "org" in dims, str(dims)),
    ]


# ---------------------------------------------------------------- 网关内部 / 管理接口
def gw_get(path: str, params: dict | None = None) -> dict:
    """网关内部与管理接口（X-Internal-Secret 即 admin）。"""
    resp = httpx.get(f"{GW}{path}", params=params,
                     headers={"X-Internal-Secret": INTERNAL_SECRET}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def gw_post(path: str, json_body: dict | None = None) -> dict:
    """网关管理写接口（注册/吊销/恢复等；非 200 抛 GwToolError 供断言）。"""
    resp = httpx.post(f"{GW}{path}", json=json_body or {},
                      headers={"X-Internal-Secret": INTERNAL_SECRET}, timeout=30)
    if resp.status_code != 200:
        err = _err_of(resp)
        raise GwToolError(err.get("code", f"HTTP {resp.status_code}"), err.get("message", ""),
                          err.get("remediation"))
    return resp.json()


def hub_get(path: str, params: dict | None = None) -> dict:
    """hub 内部接口（X-Internal-Secret）。"""
    resp = httpx.get(f"{HUB}{path}", params=params,
                     headers={"X-Internal-Secret": INTERNAL_SECRET}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def health_all() -> dict[str, dict]:
    """四服务健康检查（legacy-erp-ap 用免认证的 /metadata 探针）。"""
    out = {}
    for name, url in (("gateway", f"{GW}/healthz"), ("hub", f"{HUB}/healthz"),
                      ("semantics", f"{SEM}/healthz"), ("legacy-erp-ap", f"{JAVA}/metadata")):
        try:
            resp = httpx.get(url, timeout=10)
            out[name] = {"ok": resp.status_code == 200, "status": resp.status_code}
        except httpx.HTTPError as e:
            out[name] = {"ok": False, "status": str(e)[:80]}
    return out


def collect_versions() -> dict:
    """版本四件套 + 模型网关模式（报告/自检头部）。"""
    out: dict = {}
    for key, path in (("versions", "/gw/versions"), ("modelgw", "/gw/modelgw/status")):
        try:
            out[key] = gw_get(path)
        except Exception as e:  # noqa: BLE001
            out[key] = {"error": str(e)[:80]}
    flat = dict(out.get("versions") or {})
    mode = out.get("modelgw") or {}
    flat["model"] = mode.get("model")
    flat["modelMode"] = mode.get("mode")
    return flat


# ---------------------------------------------------------------- 断言收集器
class Checks:
    """检验项收集：add() 即打印；ok 汇总决定退出码。"""

    def __init__(self, title: str):
        self.title = title
        self.items: list[dict] = []

    def __init__(self, title: str):
        self.title = title
        self.items: list[dict] = []
        self.current_group = ""

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": str(detail),
                           "group": self.current_group})
        mark = "PASS" if ok else "FAIL"
        suffix = f" —— {detail}" if detail else ""
        print(f"  [{mark}] {name}{suffix}")
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(i["ok"] for i in self.items)

    @property
    def failures(self) -> list[dict]:
        return [i for i in self.items if not i["ok"]]

    def summary(self) -> str:
        total, bad = len(self.items), len(self.failures)
        return f"{self.title}: {total - bad}/{total} 通过" + ("" if not bad else f"（失败: {bad}）")
