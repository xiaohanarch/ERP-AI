#!/usr/bin/env python3
"""第 8 幕：多领域 Agent 协同 —— AP 委派采购域的跨域根因诊断。

场景（业务驱动，不为协同而协同）：INV-A-001 被阻断，AP 侧只能看到
「发票 120 vs 收货 100」的数量差异；短交还是超开要结合采购域订单量定位
（PO-A-0001 订单 100 = 已收 100，故为供应商超开 20 件）。

  A. 跨域综合诊断：xdom.diag 一问 -> AP 归因 + 委派采购域取证 + 综合结论
  B. 委派治理（判定在网关，不在模型）：
     - 委派 T2 的 act 委托链增长 [proc-copilot -> ap-copilot -> erp-ai-hub]；
     - 子代理最小权限（T2 scope 仅采购域 2 工具）；
     - 协作清单外委派被拒（403 GW.DELEGATION_NOT_ALLOWED，双向）；
     - 审计留痕含 delegation_chain。
  C. 采购域独立可用（proc.diag 直问）+ 护栏对跨域场景同样前置。

用法: python scripts/demo/scene_8.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402

EAST = {"user": "lisi", "tenant": "T-EAST"}
UNI = {"user": "qianqi", "tenant": "T-UNI"}
PROC_TOOLS = ["proc.po.getDetail", "proc.gr.listForPo"]


def _exchange(delegated_by: str | None, agent_id: str, tools: list[str],
              username: str, tenant: str, scene: str = "proc.diag") -> tuple[int, dict]:
    """直连网关交换（带可选委派方），返回 (HTTP 状态, 响应 JSON)。"""
    body = {"agentId": agent_id, "scene": scene, "tools": tools,
            "clientId": C.HUB_CLIENT_ID, "clientSecret": C.HUB_CLIENT_SECRET,
            "username": username, "tenantId": tenant}
    if delegated_by:
        body["delegatedBy"] = delegated_by
    resp = httpx.post(f"{C.GW}/gw/auth/exchange", json=body, timeout=15)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {}


def _jwt_payload(token: str) -> dict:
    """解码 JWT payload（不验签 —— 断言 claims 内容，验签是网关的事）。"""
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def main() -> int:
    print("=== 第 8 幕：多领域 Agent 协同（AP 委派采购域） ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_8] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 8 幕")

    # ---- A. 跨域综合诊断（正向全链路） ----
    print("── 跨域综合诊断：INV-A-001 为什么被阻断？采购和收货那边什么情况？")
    t0 = (datetime.now() - timedelta(seconds=2)).isoformat(timespec="seconds")
    xchat = C.chat(EAST["user"], "xdom.diag", "INV-A-001 为什么被阻断？采购和收货那边什么情况？")
    answer = xchat["answer"]
    print(f"  综合结论（截断）：{answer[answer.find('【综合结论】'):][:130] if '【综合结论】' in answer else answer[:130]}")
    ck.add("AP 侧归因保留（QTY_MISMATCH + 120 vs 100）",
           "AP.MATCH.QTY_MISMATCH" in answer and "120" in answer and "100" in answer,
           answer[:160])
    ck.add("采购域取证到位（PO-A-0001 状态与收货）",
           "PO-A-0001" in answer and "已过账" in answer and "已收齐" in answer,
           answer[:200])
    ck.add("综合结论定位超开（根因 + 处置建议）",
           "供应商超开" in answer and "红字" in answer, answer[:200])
    tool_names = {t["tool"] for t in xchat["tools"]}
    ck.add("跨域工具链可见（AP 2 个 + 采购域 2 个）",
           {"ap.invoice.checkValidation", "ap.invoice.getMatchDetail",
            "proc.po.getDetail", "proc.gr.listForPo"} <= tool_names,
           str(sorted(tool_names)))

    # ---- B. 委派治理（网关第七道校验 + act 链） ----
    print("── 委派治理：act 委托链 / 最小权限 / 协作清单")
    code, body = _exchange("ap-copilot", "proc-copilot", PROC_TOOLS,
                           EAST["user"], EAST["tenant"])
    act = None
    if code == 200:
        claims = _jwt_payload(body["token"])
        act = claims.get("act")
        ck.add("子代理最小权限（T2 scope 仅采购域工具）",
               set(claims.get("scope") or []) == set(PROC_TOOLS)
               and "ap.invoice.checkValidation" not in (claims.get("scope") or []),
               str(claims.get("scope")))
        ck.add("act 委托链增长（proc -> ap-copilot -> hub）",
               act.get("sub") == "agent:proc-copilot"
               and (act.get("act") or {}).get("sub") == "agent:ap-copilot"
               and ((act.get("act") or {}).get("act") or {}).get("sub") == "erp-ai-hub",
               json.dumps(act, ensure_ascii=False))
    else:
        ck.add("委派交换成功", False, f"HTTP {code} {str(body)[:120]}")
        ck.add("act 委托链增长（proc -> ap-copilot -> hub）", False, "交换失败")
        ck.add("子代理最小权限（T2 scope 仅采购域工具）", False, "交换失败")

    for label, delegated_by, agent_id, tools, user, tenant, scene in (
            ("协作清单外委派被拒（ap-batch 无协作清单）", "ap-batch", "proc-copilot",
             PROC_TOOLS, EAST["user"], EAST["tenant"], "proc.diag"),
            ("反向委派被拒（proc-copilot 未声明协作）", "proc-copilot", "ap-copilot",
             ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail"],
             EAST["user"], EAST["tenant"], "xdom.diag"),
            ("跨租委派被拒（T-UNI 用户 + T-EAST 委派方）", "ap-copilot", "proc-copilot",
             PROC_TOOLS, UNI["user"], UNI["tenant"], "proc.diag")):
        code, body = _exchange(delegated_by, agent_id, tools, user, tenant, scene)
        err = body.get("error", {})
        # 跨租用例：委派方租户与用户租户不符 -> 同样拒绝（DELEGATION 或 TENANT_MISMATCH 均为正确拦截）
        ok = code == 403 and err.get("code") in ("GW.DELEGATION_NOT_ALLOWED", "GW.TENANT_MISMATCH")
        ck.add(label, ok, f"HTTP {code} {err.get('code')} {str(err.get('message', ''))[:80]}")

    audit = C.gw_get("/internal/audit", {"limit": 100})
    proc_rows = [r for r in audit.get("items", [])
                 if str(r.get("agent_id", "")).endswith("proc-copilot")
                 and str(r.get("ts", "")) >= t0]
    chained = [r for r in proc_rows if "agent:ap-copilot" in str(r.get("delegation_chain") or "")]
    ck.add("子代理工具调用留痕且携带委派链（delegation_chain）",
           len(chained) >= 1, f"时间窗内 proc-copilot {len(proc_rows)} 条，含委派链 {len(chained)} 条")

    # ---- C. 采购域独立可用 + 护栏前置 ----
    print("── 采购域独立场景 + 跨域护栏")
    pchat = C.chat(EAST["user"], "proc.diag", "PO-A-0001 的订单和收货情况怎么样？")
    ck.add("采购域独立可用（proc.diag 直问订单状态）",
           pchat["done"] and "PO-A-0001" in pchat["answer"] and "已过账" in pchat["answer"],
           pchat["answer"][:160] or str(pchat["error"]))
    gchat = C.chat(EAST["user"], "xdom.diag", "帮我把 INV-A-001 这张发票过账吧")
    err = gchat["error"] or {}
    ck.add("跨域场景护栏前置（诱导话术仍被拦）",
           gchat["error"] is not None and err.get("code") == "HUB.GUARDRAIL_BLOCKED",
           str(err)[:120])

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
