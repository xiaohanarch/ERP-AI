#!/usr/bin/env python3
"""第 5 幕：双租同题不同答 —— 语义叠加让同一问题随租户解析。

  1) 「大额风险」：T-EAST 50 万口径命中 INV-A-011 / T-UNI 500 万口径命中 INV-B-004；
  2) 「进货单」：T-EAST 解析为采购订单（PO）/ T-UNI 解析为收货单（GR）；
  3) 余额口径：T-EAST 净额不含暂估 / T-UNI 扣减暂估（差额 = 暂估不变式）。

用法: python scripts/demo/scene_5.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402

EAST = {"user": "lisi", "tenant": "T-EAST", "batch": "ap-batch"}
UNI = {"user": "qianqi", "tenant": "T-UNI", "batch": "uni-batch"}


def main() -> int:
    print("=== 第 5 幕：双租同题不同答 —— 语义叠加 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_5] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 5 幕")

    # ---- 1) 大额风险：同一句话，双租不同阈值与命中 ----
    print("── 同题：「帮我筛查大额风险的阻断发票」")
    e_chat = C.chat(EAST["user"], "ap.batch", "帮我筛查大额风险的阻断发票")
    u_chat = C.chat(UNI["user"], "ap.batch", "帮我筛查大额风险的阻断发票")
    print(f"  T-EAST 应答（截断）：{e_chat['answer'][:110]}")
    print(f"  T-UNI  应答（截断）：{u_chat['answer'][:110]}")

    ck.add("T-EAST：50 万口径 + 命中 INV-A-011",
           "500,000" in e_chat["answer"] and "INV-A-011" in e_chat["answer"])
    ck.add("T-UNI：500 万口径 + 命中 INV-B-004",
           "5,000,000" in u_chat["answer"] and "INV-B-004" in u_chat["answer"])
    ck.add("双租结果互不泄露（A 不见 INV-B / B 不见 INV-A）",
           "INV-B" not in e_chat["answer"] and "INV-A" not in u_chat["answer"])

    # ---- 2) 术语叠加：「进货单」双租不同解析 ----
    print("── 同词：「进货单」术语翻译")
    tools = ["semantic.term.translate"]
    t2e = C.exchange(EAST["batch"], "ap.batch", tools, EAST["user"], EAST["tenant"])
    t2u = C.exchange(UNI["batch"], "ap.batch", tools, UNI["user"], UNI["tenant"])
    te = C.unwrap(C.mcp_call(t2e, "semantic.term.translate", {"term": "进货单"}))
    tu = C.unwrap(C.mcp_call(t2u, "semantic.term.translate", {"term": "进货单"}))
    print(f"  T-EAST：{te.get('semantic')}（{te.get('note', '')}）")
    print(f"  T-UNI ：{tu.get('semantic')}（{tu.get('note', '')}）")
    ck.add("T-EAST「进货单」-> purchase_order", te.get("semantic") == "purchase_order")
    ck.add("T-UNI「进货单」-> goods_receipt", tu.get("semantic") == "goods_receipt")

    # ---- 3) 余额口径：派生指标随租户 ----
    print("── 同指标：ap.balance.net 双租口径")
    tools = ["ap.balance.query"]
    t2e = C.exchange(EAST["batch"], "ap.batch", tools, EAST["user"], EAST["tenant"])
    t2u = C.exchange(UNI["batch"], "ap.batch", tools, UNI["user"], UNI["tenant"])
    be = C.mcp_call(t2e, "ap.balance.query", {"metric": "ap.balance.net"})
    bu = C.mcp_call(t2u, "ap.balance.query", {"metric": "ap.balance.net"})
    for side, b in (("T-EAST", be), ("T-UNI", bu)):
        diff = Decimal(str(b["valueCnyExcludingAccrual"])) - Decimal(str(b["valueCny"]))
        accrual = Decimal(str(b["components"]["ap.payable.accrual"]))
        ck.add(f"{side} 不变式：净额(不含暂估) - 净额 = 暂估", diff == accrual,
               f"{diff} = {accrual}")
    print(f"  T-EAST：净额 {C.fmt_money(be['valueCny'])}（暂估 {C.fmt_money(be['components']['ap.payable.accrual'])}，口径不含暂估）")
    print(f"  T-UNI ：净额 {C.fmt_money(bu['valueCny'])}（暂估 {C.fmt_money(bu['components']['ap.payable.accrual'])}，口径扣减暂估）")
    ck.add("T-UNI 暂估 30 万（INV-B-006）入净额",
           Decimal(str(bu["components"]["ap.payable.accrual"])) == Decimal("300000"))
    ck.add("T-EAST 无暂估（口径差异来源）",
           Decimal(str(be["components"]["ap.payable.accrual"])) == Decimal("0"))

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
