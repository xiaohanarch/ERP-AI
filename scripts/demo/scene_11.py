#!/usr/bin/env python3
"""第 11 幕：元数据自动喂养 + 本体驱动结构（同一条管道的下行与上行）。

下行（喂养）：投影段的实体清单/标签/枚举由存量元数据 /metadata 实时生成，
人工只维护口径层（业务术语/维度）——存量元数据里有、而语义文件从未手写的
实体（PurchaseOrderLine / GoodsReceiptLine）自动出现在投影段。

上行（驱动）：本体增量段的派生字段（unpaid_cny = amount_cny - paid_cny，
声明式 compute）经构建期生成器产出 derived-fields.json，Java 侧通用求值引擎
暴露为 BO 操作 ap.invoice.getDerivedField——本体改定义、重建，API 能力随之
改变；Java 不含任何字段特定逻辑。

喂养校验驱动：漂移检测新增两条不变式——口径层术语指向的实体必须存在于
存量元数据（TERM_TARGET）；派生字段的基字段必须存在于实体元数据（DERIVED_BASE）。

用法: python scripts/demo/scene_11.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402


def main() -> int:
    print("=== 第 11 幕：元数据自动喂养 + 本体驱动结构 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_11] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 11 幕")

    # ---- A. 喂养：投影段 = 生成基础层 + 人工口径层 ----
    print("── 喂养：投影段实体清单来自存量元数据（自动生成）")
    t2 = C.exchange("ap-copilot", "ap.diag",
                    ["semantic.metadata.entities", "semantic.metadata.fields",
                     "semantic.drift.status"], "lisi", "T-EAST")
    ents = C.unwrap(C.mcp_call(t2, "semantic.metadata.entities", {}))
    live = httpx.get(f"{C.JAVA}/metadata", timeout=10).json()
    live_names = set((live.get("entities") or {}).keys())
    sem_names = {e["entity"] for e in ents.get("entities", [])}
    print(f"  语义层实体 {len(sem_names)} 个 / 存量元数据 {len(live_names)} 个；"
          f"来源={ents.get('projectionSource')}")
    ck.add("投影段实体清单与存量元数据完全一致（生成而非手写）",
           ents.get("projectionSource") == "generated" and sem_names == live_names,
           f"语义层缺: {sorted(live_names - sem_names)[:3]} 多: {sorted(sem_names - live_names)[:3]}")
    ck.add("未手写实体自动出现（PurchaseOrderLine / GoodsReceiptLine）",
           {"PurchaseOrderLine", "GoodsReceiptLine"} <= sem_names,
           "语义文件从未列出这两个实体——来自元数据生成")
    ck.add("口径层叠加生效（术语仍来自人工层）",
           any(e["entity"] == "Invoice" and "发票" in e.get("terms", [])
               for e in ents.get("entities", [])))
    r = C.unwrap(C.mcp_call(t2, "semantic.metadata.fields", {"entity": "PurchaseOrderLine"}))
    ck.add("live 实体名直查（口径层没写也能查）",
           r.get("entity") == "PurchaseOrderLine" and (r.get("fieldCount") or 0) > 0,
           str(r)[:100])

    # ---- B. 喂养校验驱动：漂移不变式（术语目标 + 派生基字段） ----
    print("── 漂移：预埋 2 处仍全检出；新不变式通过且计数可见")
    drift = C.unwrap(C.mcp_call(t2, "semantic.drift.status", {}))
    counts = drift.get("counts", {})
    kinds = {d["kind"] for d in drift.get("items", [])}
    ck.add("预埋漂移仍全检出且仅此两处",
           drift.get("drifted") is True and kinds == {"FIELD_DRIFT", "RULE_DRIFT"}
           and counts.get("drifts") == 2, str(sorted(kinds)))
    ck.add("新不变式生效（术语目标 ≥6 / 派生基字段 ≥1，且零新增漂移）",
           (counts.get("checkedTermTargets") or 0) >= 6
           and (counts.get("checkedDerivedBases") or 0) >= 1
           and not (kinds - {"FIELD_DRIFT", "RULE_DRIFT"}), str(counts))

    # ---- C. 驱动：本体派生字段成为 BO 能力 ----
    print("── 驱动：unpaid_cny（本体增量段 -> 构建期生成 -> 通用求值）")
    t2d = C.exchange("ap-copilot", "ap.diag", ["ap.invoice.getDerivedField"], "lisi", "T-EAST")
    d = C.unwrap(C.mcp_call(t2d, "ap.invoice.getDerivedField",
                            {"invoiceNo": "INV-A-001", "fieldName": "unpaid_cny"}))
    print(f"  unpaid_cny = {d.get('value')}（{d.get('formula')}，本体版本 {d.get('ontologyVersion')}）")
    ck.add("派生字段值正确（3400 - 0 = 3400，含基字段取证）",
           str(d.get("value")) == "3400.00" or float(d.get("value", -1)) == 3400.0,
           str(d.get("value")))
    ck.add("本体驱动取证（基字段/公式/语义版本/驱动来源）",
           d.get("baseFields") == ["amount_cny", "paid_cny"]
           and d.get("formula") == "amount_cny - paid_cny"
           and d.get("ontologyVersion") == "ap-sem-1.1.0"
           and "ontology" in str(d.get("drivenBy", "")),
           str({k: d.get(k) for k in ("baseFields", "ontologyVersion")}))
    try:
        C.mcp_call(t2d, "ap.invoice.getDerivedField",
                   {"invoiceNo": "INV-A-001", "fieldName": "nope_cny"})
        ck.add("未在本体定义的字段被拒（AP.DERIVED_FIELD_NOT_FOUND）", False, "未拒绝")
    except Exception as e:  # noqa: BLE001 —— C.GwToolError
        ck.add("未在本体定义的字段被拒（AP.DERIVED_FIELD_NOT_FOUND）",
               "AP.DERIVED_FIELD_NOT_FOUND" in str(e), str(e)[:100])

    audit = C.gw_get("/internal/audit", {"limit": 40})
    rows = [r for r in audit.get("items", [])
            if r.get("action") == "ap.invoice.getDerivedField"
            and str(r.get("agent_id", "")).endswith("ap-copilot")]
    ck.add("派生字段调用全程留痕（T2/T3 + 审计）", len(rows) >= 1, f"{len(rows)} 条")

    versions = C.gw_get("/gw/versions")
    ck.add("版本链同步演进（spec 1.2.0 / 语义 ap-sem-1.1.0）",
           versions.get("specVersion") == "1.2.0"
           and versions.get("semanticsVersion") == "ap-sem-1.1.0",
           f"spec={versions.get('specVersion')} sem={versions.get('semanticsVersion')}")

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
