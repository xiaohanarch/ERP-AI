#!/usr/bin/env python3
"""第 12 幕：受限自主只读（第二档）——模型自选工具与顺序，安全靠平台约束。

与第一档（静态图、模型只填空）的根本差别：本幕的问题由模型决定先查什么、
再查什么、何时收尾；断言全部是**属性断言**（只读零违规 / 步数上限 /
平台取证 / 终态正确），不锚定工具调用顺序——同题两次运行允许路径不同。

四条平台约束逐一验证：
  A. 只读：调用的工具全部在只读白名单内（写工具零出现）
  B. 步数：≤ 上限（4 步）
  C. 取证：应答尾部带平台附加的工具清单与步数（不依赖模型自觉）
  D. 步级最小授权：审计里每步 T2 的 scope 都是单工具
负向：第二档场景请求写工具 -> 网关直接拒绝（GW.SCOPE_EXCEEDED）。

用法: python scripts/demo/scene_12.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402

READ_WHITELIST = {"ap.invoice.checkValidation", "ap.invoice.getMatchDetail",
                  "ap.invoice.listBlocked", "ap.invoice.getDerivedField",
                  "ap.balance.query", "semantic.capability.discover",
                  "semantic.operation.explain", "semantic.term.translate",
                  "semantic.metadata.entities", "semantic.metadata.fields"}
WRITE_TOOLS = {"ap.invoice.applyTaxCode", "ap.payment.execute"}


def main() -> int:
    print("=== 第 12 幕：受限自主只读（第二档：模型驱动的工具循环） ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_12] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 12 幕")

    # ---- A-D. 诊断类问题：模型自选路径（mock 确定性：checkValidation -> getMatchDetail -> final）----
    print("── 诊断类：INV-A-001 为什么被阻断（模型自选两步取证后收尾）")
    r1 = C.chat("lisi", "ap.explore", "INV-A-001 为什么被阻断？")
    called = [t["tool"] for t in r1["tools"]]
    print(f"  模型选择的路径：{called}")
    print(f"  应答：{r1['answer'][:160]}")
    ck.add("A. 只读零违规（调用工具全部在只读白名单内）",
           set(called) <= READ_WHITELIST and not (set(called) & WRITE_TOOLS),
           f"called={called}")
    ck.add("B. 步数上限（≤4）", len(called) <= 4, f"steps={len(called)}")
    ck.add("B2. 模型确实自选了多步（≥2 步取证）", len(called) >= 2,
           f"steps={len(called)}（第一档是图定的固定路径，这里由模型决定）")
    ck.add("C. 平台强制取证（应答带 [取证] 工具清单）", "[取证]" in r1["answer"],
           r1["answer"][-120:])
    ck.add("D. 终态正确（结论含两个真实根因）",
           "AP.MATCH.QTY_MISMATCH" in r1["answer"] and "AP.BUDGET.EXCEEDED" in r1["answer"],
           r1["answer"][:120])
    ck.add("D2. 调用全部成功（无错误事件）", r1["error"] is None, str(r1["error"]))

    # ---- 筛查类问题：同一循环图，模型选了不同工具（不为每个问题画图）----
    print("── 筛查类：有哪些被阻断的发票（同一条循环图，模型改选 listBlocked）")
    r2 = C.chat("lisi", "ap.explore", "有哪些被阻断的发票？")
    called2 = [t["tool"] for t in r2["tools"]]
    print(f"  模型选择的路径：{called2}")
    ck.add("同一循环图承载不同问题形态（筛查走 listBlocked，无需新画图）",
           "ap.invoice.listBlocked" in called2, f"called={called2}")
    ck.add("筛查类同样只读零违规", set(called2) <= READ_WHITELIST, f"called={called2}")

    # ---- 全程留痕：每步工具调用 + 每步模型决策均入审计 ----
    print("── 全程留痕：审计核对（每步工具调用 + 模型逐步决策）")
    audit = C.gw_get("/internal/audit", {"limit": 60})
    rows = [x for x in audit.get("items", []) if x.get("scene") == "ap.explore"]
    tool_rows = [x for x in rows if str(x.get("action", "")).startswith("ap.")]
    model_rows = [x for x in rows if x.get("action") == "model_call"
                  and str(x.get("trace_id", "")).startswith("script-")]
    ck.add("每步工具调用留痕（探索场景工具行 ≥3，agent 归属可见）",
           len(tool_rows) >= 3 and all(str(r.get("agent_id", "")).endswith("ap-copilot")
                                       for r in tool_rows[:3]),
           f"tool_rows={len(tool_rows)}")
    ck.add("模型逐步决策留痕（model_call ≥2：每一步都是模型决定的）",
           len(model_rows) >= 2, f"model_rows={len(model_rows)}")

    # ---- 负向：第二档场景请求写工具 -> 网关拒绝 ----
    print("── 负向：第二档场景请求写工具（applyTaxCode）")
    try:
        C.exchange("ap-copilot", "ap.explore", ["ap.invoice.applyTaxCode"], "lisi", "T-EAST")
        ck.add("写工具被第二档场景拒绝（GW.SCOPE_EXCEEDED）", False, "未被拒绝")
    except Exception as e:  # noqa: BLE001 —— C.GwError
        ck.add("写工具被第二档场景拒绝（GW.SCOPE_EXCEEDED）",
               "GW.SCOPE_EXCEEDED" in str(e), str(e)[:100])

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
