#!/usr/bin/env python3
"""第 1 幕：事故复现 —— 同一份数据，三种口径。

张三在 ERP 页面看到 ~50 条；同一租户的 Open API（appid 直连、租户级）
返回 5000+ 条（无组织过滤 —— 事故口径）；copilot/无头脚本走 BO API，
与页面共享同一权限组件，返回同口径子集并披露过滤维度。

用法: python scripts/demo/scene_1.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402


def main() -> int:
    print("=== 第 1 幕：事故复现 —— 同一份数据，三种口径 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_1] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 1 幕")

    print("── 准备：bulk 种子（幂等，已有则跳过）")
    seeded = C.bulk_seed("T-EAST", 5000)
    print(f"  本次插入 {seeded['inserted']} 条（目标 {seeded['target']}；0 = 已存在）")

    print("── 取证：三口径并发查询（张三，T-EAST）")
    c = C.three_calibers("zhangsan", "T-EAST")
    bo = c["bo"]
    ratio = c["openapiTotal"] / c["uiTotal"] if c["uiTotal"] else 0
    print("  | 口径 | 行数 | 权限语义 |")
    print("  |---|---|---|")
    print(f"  | ERP 页面（会话 + 组织过滤） | {c['uiTotal']} | 张三仅见 ORG-EAST-PROC |")
    print(f"  | Open API（appid 直连，租户级） | {c['openapiTotal']} | 事故口径：无组织过滤 |")
    print(f"  | BO API（T3，与页面同权限） | {bo['total']}（阻断子集） | + filteredByDimension 披露 |")
    print(f"  放大倍数：×{ratio:.0f}")
    print(f"  BO 命中（前 8）：{', '.join(bo['items'][:8])}")

    for name, ok, detail in C.caliber_checks(c):
        ck.add(name, ok, detail)

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
