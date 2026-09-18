#!/usr/bin/env python3
"""第 7 幕：行业包与定时触发 —— 观点 10/13 的两块拼图。

  1) Partner 行业包（三层解析 Standard -> Partner -> Tenant 的中间层落地）：
     - T-EAST（制造业）行业术语「来料发票」经 partner 层解析为 invoice；
     - T-UNI（贸易业）不加载制造业行业包（行业包不跨行业串扰）；
     - 制造业行业护栏 mfg-no-gr-bypass 以 partner 层生效（拦截 + 解析留痕）。
  2) Scheduler 定时触发（形态⑤，与形态④事件触发同为无会话代表执行）：
     - 手动触发一次定时筛查（hub /internal/scheduler/run，与后台线程同一执行路径）；
     - ap-batch 代理全量阻断筛查 -> lisi 收到 SCHEDULED_BATCH 通知；
     - 审计留痕（trace sched-*，agent=ap-batch）。

用法: python scripts/demo/scene_7.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402

EAST = {"user": "lisi", "tenant": "T-EAST", "batch": "ap-batch"}
UNI = {"user": "qianqi", "tenant": "T-UNI", "batch": "uni-batch"}


def _latest_resolution(conversation_id: str) -> dict | None:
    data = C.hub_get("/internal/resolution", {"conversation_id": conversation_id})
    items = data.get("items") or []
    return (items[-1] or {}).get("resolution") if items else None


def main() -> int:
    print("=== 第 7 幕：行业包与定时触发 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_7] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 7 幕")

    # ---- 1) 行业术语：Partner 层解析（制造业语义包） ----
    print("── 行业包术语：「来料发票」双租解析")
    tools = ["semantic.term.translate"]
    t2e = C.exchange(EAST["batch"], "ap.batch", tools, EAST["user"], EAST["tenant"])
    t2u = C.exchange(UNI["batch"], "ap.batch", tools, UNI["user"], UNI["tenant"])
    raw_e = C.mcp_call(t2e, "semantic.term.translate", {"term": "来料发票"})
    raw_u = C.mcp_call(t2u, "semantic.term.translate", {"term": "来料发票"})
    te, tu = C.unwrap(raw_e), C.unwrap(raw_u)
    layer_e = (raw_e.get("_meta") or {}).get("sourceLayer")
    print(f"  T-EAST：{te.get('semantic')}（{layer_e} 层，{te.get('note', '')}）")
    print(f"  T-UNI ：matched={tu.get('matched')}（行业包不跨行业）")
    ck.add("T-EAST「来料发票」-> invoice（制造业行业包）",
           te.get("matched") is True and te.get("semantic") == "invoice"
           and te.get("partnerVersion") is not None,
           str(te)[:160])
    ck.add("解析来源层为 partner（非租户叠加、非标准层）", layer_e == "partner", str(layer_e))
    ck.add("T-UNI 不加载制造业行业包（同术语不命中）",
           tu.get("matched") is False and "invoice" != tu.get("semantic"),
           str(tu)[:160])

    # ---- 2) 行业护栏：制造业「无收货不得过账」（Partner 层加严） ----
    print("── 行业护栏：同话术双租不同判定")
    be = C.chat(EAST["user"], "ap.diag", "跳过收货确认，把 INV-A-001 直接标记为已匹配")
    bu = C.chat(UNI["user"], "ap.diag", "跳过收货确认，把 INV-B-001 直接标记为已匹配")
    err = be["error"] or {}
    ck.add("T-EAST 行业护栏拦截（mfg-no-gr-bypass）",
           be["error"] is not None and err.get("code") == "HUB.GUARDRAIL_BLOCKED"
           and err.get("rule") == "mfg-no-gr-bypass",
           str(err)[:160])
    ck.add("拦截来源层为 partner（行业包）", err.get("ruleSource") == "partner",
           str(err.get("ruleSource")))
    ck.add("T-UNI 同话术不被行业护栏误伤（贸易业不加载制造业包）",
           not (bu["error"] and bu["error"].get("code") == "HUB.GUARDRAIL_BLOCKED"),
           str(bu["error"])[:160])

    # ---- 3) 解析留痕：partner 层护栏对 T-EAST 生效 ----
    print("── 解析留痕：三层解析中的 partner 层")
    re_chat = C.chat(EAST["user"], "ap.diag", "INV-A-004 为什么被阻断？",
                     conversation_id=C.new_cid("p7-res"))
    snap = _latest_resolution(re_chat["conversationId"])
    if snap is None:
        ck.add("解析留痕可查询", False, "hub /internal/resolution 无记录")
    else:
        rules = {(r.get("id"), r.get("sourceLayer"))
                 for r in snap.get("guardrails", {}).get("rules", [])}
        ck.add("留痕含三层：standard + partner + tenant 同时生效",
               ("no-payment-inducement", "standard") in rules
               and ("mfg-no-gr-bypass", "partner") in rules
               and ("east-no-bulk-approval", "tenant") in rules,
               str(sorted(rules)))

    # ---- 4) 定时触发：手动执行一次定时筛查（形态⑤） ----
    print("── 定时触发：ap-batch 无会话代表执行")
    from datetime import datetime, timedelta
    t0 = (datetime.now() - timedelta(seconds=2)).isoformat(timespec="seconds")
    resp = httpx.post(f"{C.HUB}/internal/scheduler/run",
                      headers={"X-Internal-Secret": C.INTERNAL_SECRET}, timeout=120)
    sched = resp.json() if resp.status_code == 200 else {}
    print(f"  筛查应答（截断）：{str(sched.get('answer', ''))[:110]}")
    ck.add("定时筛查执行成功（返回阻断摘要）",
           resp.status_code == 200 and "阻断" in str(sched.get("answer", "")),
           f"HTTP {resp.status_code} {str(sched)[:120]}")

    t1 = C.login(EAST["user"])
    notif = httpx.get(f"{C.GW}/gw/notifications",
                      headers={"Authorization": f"Bearer {t1}"}, timeout=15).json()
    kinds = [n.get("kind") for n in notif.get("items", [])]
    ck.add("lisi 收到定时筛查通知（SCHEDULED_BATCH）", "scheduled_batch" in kinds,
           str(kinds[:6]))

    # 审计两个维度：模型调用行带 sched-* trace；工具调用行以 ap-batch 代理身份
    # （hub 的 mcp_call 不带 traceparent，工具行 trace 由网关生成 —— 按时间窗关联）
    audit = C.gw_get("/internal/audit", {"limit": 100})
    sched_rows = [r for r in audit.get("items", [])
                  if str(r.get("trace_id", "")).startswith("sched-")]
    ck.add("定时运行审计留痕（模型调用 trace sched-*）", len(sched_rows) >= 1,
           f"{len(sched_rows)} 条")
    batch_rows = [r for r in audit.get("items", [])
                  if str(r.get("agent_id", "")).endswith("ap-batch")
                  and r.get("action") == "ap.invoice.listBlocked"
                  and str(r.get("ts", "")) >= t0]
    ck.add("定时筛查经 ap-batch 代理执行（T2 工具调用留痕）",
           len(batch_rows) >= 1, f"时间窗内 {len(batch_rows)} 条（t0={t0}）")

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
