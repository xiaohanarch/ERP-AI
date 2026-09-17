#!/usr/bin/env python3
"""bulk 种子：向存量域追加 bulk 发票（事故端点演示数据）。

幂等：BulkSeeder.ensureBulk 已有则跳过（重复执行零副作用）。
用法: python scripts/seed_bulk.py [--tenant T-EAST] [--count 5000]
"""
from __future__ import annotations

import argparse
import sys

import _common as C


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="T-EAST", choices=["T-EAST", "T-UNI"])
    ap.add_argument("--count", type=int, default=5000)
    args = ap.parse_args()

    print(f"[seed_bulk] 向 {args.tenant} 追加 bulk 发票（目标 {args.count} 条，幂等）...")
    try:
        seeded = C.bulk_seed(args.tenant, args.count)
    except Exception as e:  # noqa: BLE001
        print(f"[seed_bulk] 失败：{e}")
        return 1
    print(f"[seed_bulk] 本次插入 {seeded['inserted']} 条（目标 {seeded['target']}；0 = 已存在）")

    open_stats = C.openapi_invoices(args.tenant)
    print(f"[seed_bulk] Open API 口径当前总量：{open_stats['total']} 条（租户级、无组织过滤）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
