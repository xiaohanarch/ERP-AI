#!/usr/bin/env python3
"""多租六项检验（独立退出码）。

  A. A0 叠加    大额阈值命中集合 + 取值来源取证（租户层叠加 vs Standard 层）
  B. 术语叠加   同一业务术语双租不同解析（进货单 -> purchase_order / goods_receipt）
  C. 派生指标   余额口径「差额 = 暂估」不变式 + 双租净额口径差异
  D. 三层解析   解析留痕可视化（Standard->Tenant 层命中 + 放松类叠加被拒）
  E. 跨租隔离   NOT_FOUND 不泄露存在性 + TENANT_MISMATCH + 结果集防串扰
  F. 成本归集   双租分离 + 与审计对账（audit model_call vs cost_ledger）

用法: python scripts/tenant_checks.py
退出码: 0 = 六项全绿；1 = 任一检验失败；2 = 服务不可达。
报告: eval/reports/tenant-checks-latest.{json}（生成物，不入库）。
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import _common as C

REPORT = Path(C.REPO) / "eval" / "reports" / "tenant-checks-latest.json"

EAST = {"user": "lisi", "tenant": "T-EAST", "batch_agent": "ap-batch", "diag_agent": "ap-copilot"}
UNI = {"user": "qianqi", "tenant": "T-UNI", "batch_agent": "uni-batch", "diag_agent": "uni-copilot"}


def _t2(side: dict, tools: list[str]) -> str:
    return C.exchange(side["batch_agent"], "ap.batch", tools, side["user"], side["tenant"])


# ---------------------------------------------------------------- 检验 A
def check_a0(ck: C.Checks, ctx: dict) -> None:
    print("── 检验 A：A0 叠加（阈值来源取证 + 命中集合）")
    tools = ["semantic.metric.get", "ap.invoice.listBlocked"]
    t2e, t2u = _t2(EAST, tools), _t2(UNI, tools)

    me = C.unwrap(C.mcp_call(t2e, "semantic.metric.get", {"metric": "large_risk_amount"}))
    mu = C.unwrap(C.mcp_call(t2u, "semantic.metric.get", {"metric": "large_risk_amount"}))
    ce, cu = me["caliber"], mu["caliber"]

    ck.add("T-EAST 大额阈值 = 500,000", ce["threshold"] == 500000,
           f"实际 {ce['threshold']}")
    ck.add("T-EAST 阈值来自租户叠加层（取证）",
           me["caliberSource"]["layer"] == "tenant" and "华东制造" in ce["thresholdSource"],
           f"layer={me['caliberSource']['layer']}，source={ce['thresholdSource']}")
    ck.add("T-UNI 大额阈值 = 5,000,000", cu["threshold"] == 5000000,
           f"实际 {cu['threshold']}")
    ck.add("T-UNI 阈值来自租户叠加层（取证）",
           mu["caliberSource"]["layer"] == "tenant" and "星联科技" in cu["thresholdSource"],
           f"layer={mu['caliberSource']['layer']}，source={cu['thresholdSource']}")

    le = C.mcp_call(t2e, "ap.invoice.listBlocked", {"minAmountCny": 500000, "pageSize": 100})
    lu = C.mcp_call(t2u, "ap.invoice.listBlocked", {"minAmountCny": 5000000, "pageSize": 100})
    east_set = {i["invoiceNo"] for i in le["items"]}
    uni_set = {i["invoiceNo"] for i in lu["items"]}

    ck.add("T-EAST 50 万口径命中 INV-A-011", "INV-A-011" in east_set,
           f"命中 {sorted(east_set)}")
    ck.add("T-UNI 500 万口径命中 INV-B-004", "INV-B-004" in uni_set,
           f"命中 {sorted(uni_set)}")
    ck.add("同阈值语义下双租命中集合互不相交", not (east_set & uni_set))

    ctx["east_large"] = east_set
    ctx["uni_large"] = uni_set

    # 全量清单防串扰 + 数据权限维度披露（E-2）
    fe = C.mcp_call(t2e, "ap.invoice.listBlocked", {"pageSize": 100})
    fu = C.mcp_call(t2u, "ap.invoice.listBlocked", {"pageSize": 100})
    fe_all_a = bool(fe["items"]) and all(i["invoiceNo"].startswith("INV-A-") for i in fe["items"])
    fu_all_b = bool(fu["items"]) and all(i["invoiceNo"].startswith("INV-B-") for i in fu["items"])
    ck.add("T-EAST 阻断清单仅含本租发票（INV-A-*）", fe_all_a,
           f"{len(fe['items'])} 条")
    ck.add("T-UNI 阻断清单仅含本租发票（INV-B-*）", fu_all_b,
           f"{len(fu['items'])} 条")
    ck.add("批量筛查响应携带 filteredByDimension 披露",
           bool(fe.get("filteredByDimension")) and bool(fu.get("filteredByDimension")))


# ---------------------------------------------------------------- 检验 B
def check_terms(ck: C.Checks, ctx: dict) -> None:
    print("── 检验 B：术语叠加（同一术语，双租不同解析）")
    tools = ["semantic.term.translate"]
    t2e, t2u = _t2(EAST, tools), _t2(UNI, tools)

    te = C.unwrap(C.mcp_call(t2e, "semantic.term.translate", {"term": "进货单"}))
    tu = C.unwrap(C.mcp_call(t2u, "semantic.term.translate", {"term": "进货单"}))

    ck.add("T-EAST「进货单」-> purchase_order（PO）",
           te.get("matched") and te.get("semantic") == "purchase_order",
           te.get("note", ""))
    ck.add("T-UNI「进货单」-> goods_receipt（GR）",
           tu.get("matched") and tu.get("semantic") == "goods_receipt",
           tu.get("note", ""))
    ck.add("同题不同答：双租解析结果不同",
           te.get("semantic") != tu.get("semantic"),
           f"{te.get('semantic')} vs {tu.get('semantic')}")


# ---------------------------------------------------------------- 检验 C
def check_metrics(ck: C.Checks, ctx: dict) -> None:
    print("── 检验 C：派生指标（差额 = 暂估不变式 + 双租口径差异）")
    tools = ["ap.balance.query", "semantic.metric.get"]
    t2e, t2u = _t2(EAST, tools), _t2(UNI, tools)

    be = C.mcp_call(t2e, "ap.balance.query", {"metric": "ap.balance.net"})
    bu = C.mcp_call(t2u, "ap.balance.query", {"metric": "ap.balance.net"})

    for name, b in (("T-EAST", be), ("T-UNI", bu)):
        comp = b["components"]
        diff = Decimal(str(b["valueCnyExcludingAccrual"])) - Decimal(str(b["valueCny"]))
        accrual = Decimal(str(comp["ap.payable.accrual"]))
        ck.add(f"{name} 不变式：净额(不含暂估) - 净额 = 暂估", diff == accrual,
               f"差额 {diff} = 暂估 {accrual}")

    uni_accrual = Decimal(str(bu["components"]["ap.payable.accrual"]))
    ck.add("T-UNI 存在暂估发票（INV-B-006，30 万）", uni_accrual == Decimal("300000"),
           f"暂估合计 {uni_accrual}")

    me = C.unwrap(C.mcp_call(t2e, "semantic.metric.get", {"metric": "net_payable"}))
    mu = C.unwrap(C.mcp_call(t2u, "semantic.metric.get", {"metric": "net_payable"}))
    ce, cu = me["caliber"], mu["caliber"]
    ck.add("T-EAST 净额口径不含暂估（confirmed - paid）",
           ce.get("formula") == "confirmed - paid" and ce.get("includesAccrual") is False,
           f"{ce.get('formula')}（{me['caliberSource']['layer']} 层）")
    ck.add("T-UNI 净额口径扣减暂估（confirmed - paid - accrual）",
           cu.get("formula") == "confirmed - paid - accrual" and cu.get("includesAccrual") is True,
           f"{cu.get('formula')}（{mu['caliberSource']['layer']} 层）")
    ck.add("余额指标出口带口径说明（语义层不生成 SQL）", "口径" in str(be.get("caliber", "")))


# ---------------------------------------------------------------- 检验 D
def check_resolution(ck: C.Checks, ctx: dict) -> None:
    print("── 检验 D：三层解析可视化（含放松类叠加被拒）")
    re_chat = C.chat(EAST["user"], "ap.diag", "INV-A-004 为什么被阻断？",
                     conversation_id=C.new_cid("res-east"))
    ck.add("T-EAST 解析留痕会话完成", re_chat["done"] and re_chat["error"] is None,
           re_chat["error"]["code"] if re_chat["error"] else re_chat["conversationId"])
    ru_chat = C.chat(UNI["user"], "ap.diag", "INV-B-001 校验情况怎么样？",
                     conversation_id=C.new_cid("res-uni"))

    re_snap = _latest_resolution(re_chat["conversationId"])
    ru_snap = _latest_resolution(ru_chat["conversationId"])
    if re_snap is None or ru_snap is None:
        ck.add("解析留痕可查询", False, "hub /internal/resolution 无记录")
        return

    e_rules = {(r["id"], r["sourceLayer"]) for r in re_snap["guardrails"]["rules"]}
    ck.add("T-EAST 命中 Standard 层护栏（no-payment-inducement）",
           ("no-payment-inducement", "standard") in e_rules, str(sorted(e_rules)))
    ck.add("T-EAST 命中租户加严护栏（east-no-bulk-approval，tenant 层）",
           ("east-no-bulk-approval", "tenant") in e_rules)
    rejected = re_snap["guardrails"]["rejectedOverlays"]
    ck.add("放松类租户叠加被拒（护栏只能加严）", len(rejected) >= 1,
           "; ".join(str(r.get("overlay") or r.get("asset") or r)[:60] for r in rejected[:2]))

    u_rules = {(r["id"], r["sourceLayer"]) for r in ru_snap["guardrails"]["rules"]}
    ck.add("T-UNI 不加载 T-EAST 加严护栏（租户叠加不串扰）",
           ("east-no-bulk-approval", "tenant") not in u_rules, str(sorted(u_rules)))
    ck.add("解析留痕包含提示词资产清单", bool(re_snap.get("prompt", {}).get("assets")))


def _latest_resolution(conversation_id: str) -> dict | None:
    data = C.hub_get("/internal/resolution", {"conversation_id": conversation_id})
    items = data.get("items") or []
    return items[0]["resolution"] if items else None


# ---------------------------------------------------------------- 检验 E
def check_isolation(ck: C.Checks, ctx: dict) -> None:
    print("── 检验 E：跨租隔离（NOT_FOUND + TENANT_MISMATCH + 防串扰）")
    # 1) 跨租查询按不存在处理（不泄露存在性）
    ze = C.chat("zhangsan", "ap.diag", "INV-B-001 为什么被阻断？")
    ck.add("张三(T-EAST) 查 INV-B-001 -> AP.INVOICE_NOT_FOUND",
           ze["error"] and ze["error"]["code"] == "AP.INVOICE_NOT_FOUND",
           ze["error"]["code"] if ze["error"] else "未报错")
    # 用户自己输入的单据号回显不算泄露；泄露标志是 B 租实体信息（公司名/组织/供应商）
    ck.add("应答不泄露 B 租实体信息（星联/ORG-B/SUP-B）",
           not any(m in ze["answer"] for m in ("星联", "ORG-B", "SUP-B")))

    zu = C.chat("zhaoliu", "ap.diag", "INV-A-001 为什么被阻断？")
    ck.add("赵六(T-UNI) 查 INV-A-001 -> AP.INVOICE_NOT_FOUND",
           zu["error"] and zu["error"]["code"] == "AP.INVOICE_NOT_FOUND",
           zu["error"]["code"] if zu["error"] else "未报错")

    # 2) 令牌交换层租户不匹配被拒
    try:
        C.exchange("uni-copilot", "ap.diag",
                   ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail"],
                   "lisi", "T-EAST")
        ck.add("跨租 Agent 交换被拒（GW.TENANT_MISMATCH）", False, "未被拒绝")
    except C.GwError as e:
        ck.add("跨租 Agent 交换被拒（GW.TENANT_MISMATCH）", e.code == "GW.TENANT_MISMATCH",
               f"{e.code}: {e.message}")

    # 3) 结果集防串扰（大额命中集合互不相交；全量清单前缀纯净）
    ck.add("大额命中集合防串扰（A 检验取证）",
           not (ctx.get("east_large", set()) & ctx.get("uni_large", set())))


# ---------------------------------------------------------------- 检验 F
def check_cost(ck: C.Checks, ctx: dict) -> None:
    print("── 检验 F：成本归集（双租分离 + 审计对账）")
    before = {}
    for side in (EAST, UNI):
        before[side["tenant"]] = C.gw_get("/internal/cost", {"tenant_id": side["tenant"]})["summary"]["calls"]

    # 双租各发起一次真实模型调用（自含，不依赖历史数据）
    C.chat(EAST["user"], "ap.diag", "INV-A-002 校验情况怎么样？")
    C.chat(UNI["user"], "ap.diag", "INV-B-001 校验情况怎么样？")

    after = {}
    for side in (EAST, UNI):
        after[side["tenant"]] = C.gw_get("/internal/cost", {"tenant_id": side["tenant"]})["summary"]["calls"]
        ck.add(f"{side['tenant']} 成本台账新增本次调用",
               after[side["tenant"]] > before[side["tenant"]],
               f"{before[side['tenant']]} -> {after[side['tenant']]}")

    # 明细租户纯度
    for side in (EAST, UNI):
        detail = C.gw_get("/internal/cost", {"tenant_id": side["tenant"], "limit": 50})
        pure = all(i["tenantId"] == side["tenant"] for i in detail["items"])
        ck.add(f"{side['tenant']} 成本明细租户纯净", pure, f"{len(detail['items'])} 条抽样")

    # 与审计对账（model_call 事件数 vs 台账行数）
    summary = C.gw_get("/gw/cost/summary")
    recon = summary.get("reconciliation", {})
    for tenant in ("T-EAST", "T-UNI"):
        r = recon.get(tenant)
        ck.add(f"{tenant} 成本-审计对账一致", bool(r and r.get("match")),
               f"cost={r.get('costCalls')} audit={r.get('auditModelCalls')}" if r else "无记录")
    ck.add("双租成本各自归集（均有计量）",
           all(recon.get(t, {}).get("costCalls", 0) > 0 for t in ("T-EAST", "T-UNI")))


CHECKS = [
    ("A0 叠加", check_a0),
    ("术语叠加", check_terms),
    ("派生指标", check_metrics),
    ("三层解析", check_resolution),
    ("跨租隔离", check_isolation),
    ("成本归集", check_cost),
]


def main() -> int:
    print("=== 多租六项检验（tenant_checks）===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[tenant_checks] 服务不可达：{down} —— 请先启动 compose")
        return 2

    ck = C.Checks("多租六项")
    ctx: dict = {}
    for title, fn in CHECKS:
        ck.current_group = title
        try:
            fn(ck, ctx)
        except Exception as e:  # noqa: BLE001 —— 单项异常不阻断其余检验
            ck.add(f"{title}（执行异常）", False, str(e)[:160])

    print(f"\n{ck.summary()}")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "title": "多租六项检验", "passed": len(ck.items) - len(ck.failures),
        "total": len(ck.items), "ok": ck.ok,
        "items": ck.items, "checkedAt": C.run_id(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[tenant_checks] 报告 -> {REPORT}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
