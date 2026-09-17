#!/usr/bin/env python3
"""第 2 幕：completeness 披露 —— 同一张发票，两种视角。

INV-A-001 同时存在数量差异（MATCH）与预算超支（BUDGET）：
  - 张三（采购经理，无 ap.budget.read）：只看到数量差异 + 「预算校验未执行」披露；
  - 李四（财务，全权限）：看到完整结论（含预算超支）。
存量现状是「权限不足静默跳过规则组」；BO API 适配层补齐为 completeness 披露。

用法: python scripts/demo/scene_2.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402


def main() -> int:
    print("=== 第 2 幕：completeness 披露 —— 同一张发票，两种视角 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_2] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 2 幕")

    # ---- 1) 无头口径（确定性）：同一工具、两个身份 ----
    print("── BO API 直查 ap.invoice.checkValidation（INV-A-001）")
    t2_z = C.exchange("ap-headless", "ap.diag", ["ap.invoice.checkValidation"], "zhangsan", "T-EAST")
    t2_l = C.exchange("ap-copilot", "ap.diag", ["ap.invoice.checkValidation"], "lisi", "T-EAST")
    rz = C.mcp_call(t2_z, "ap.invoice.checkValidation", {"invoiceNo": "INV-A-001"})
    rl = C.mcp_call(t2_l, "ap.invoice.checkValidation", {"invoiceNo": "INV-A-001"})
    cz, cl = rz["completeness"], rl["completeness"]
    z_findings = {f["ruleId"] for f in rz["findings"]}
    l_findings = {f["ruleId"] for f in rl["findings"]}

    print(f"  张三：overall={rz['overallResult']} findings={sorted(z_findings)} "
          f"completeness.full={cz['full']} skipped={cz['skippedRuleGroups']}")
    print(f"  李四：overall={rl['overallResult']} findings={sorted(l_findings)} "
          f"completeness.full={cl['full']} skipped={cl['skippedRuleGroups']}")

    ck.add("张三：MATCH 数量差异可见（AP.MATCH.QTY_MISMATCH）", "AP.MATCH.QTY_MISMATCH" in z_findings)
    ck.add("张三：预算超支不可见（无 ap.budget.read）", "AP.BUDGET.EXCEEDED" not in z_findings)
    ck.add("张三：completeness 披露 BUDGET 组未执行",
           cz["full"] is False and "BUDGET" in cz["skippedRuleGroups"]
           and "不代表完整校验结论" in str(cz.get("note", "")),
           f"skipped={cz['skippedRuleGroups']}")
    ck.add("李四：完整结论（MATCH + BUDGET 双发现）",
           "AP.MATCH.QTY_MISMATCH" in l_findings and "AP.BUDGET.EXCEEDED" in l_findings
           and cl["full"] is True)

    # ---- 2) copilot 叙事口径（页面内嵌助手） ----
    print("── copilot 对话（同一问题，双视角）")
    z_chat = C.chat("zhangsan", "ap.diag", "INV-A-001 为什么会被拦下来？")
    l_chat = C.chat("lisi", "ap.diag", "INV-A-001 为什么会被拦下来？")
    print(f"  张三应答（截断）：{z_chat['answer'][:120]}")
    print(f"  李四应答（截断）：{l_chat['answer'][:120]}")

    ck.add("张三 copilot：明示校验不完整（不静默）",
           z_chat["done"] and "校验不完整" in z_chat["answer"] and "BUDGET" in z_chat["answer"])
    ck.add("张三 copilot：不泄露预算超支发现", "AP.BUDGET.EXCEEDED" not in z_chat["answer"])
    ck.add("李四 copilot：结论含预算超支", "AP.BUDGET.EXCEEDED" in l_chat["answer"])

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
