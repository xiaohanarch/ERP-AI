# 本地功能自测：模拟存量元数据（真实集成在 Docker 冒烟中做）
import sys

from service import loader, tools

FAKE_LIVE = {
    "appid": "erp-ap", "domain": "AP",
    "ruleSetVersion": "AP-RS-1.2.0", "seedVersion": "ap-seed-1.0.0",
    "entities": {
        "Invoice": {"label": "应付发票", "fields": [
            {"name": "invoice_no", "type": "string", "label": "发票号"},
            {"name": "supplier", "type": "string", "label": "供应商"},
            {"name": "amount_cny", "type": "number", "label": "金额"},
            {"name": "is_accrual", "type": "boolean", "label": "暂估标记"},
        ]},
        "Supplier": {"label": "供应商", "fields": [
            {"name": "supplier_code", "type": "string", "label": "供应商编码"},
        ]},
    },
    "rules": [
        {"ruleId": "AP.MATCH.QTY_MISMATCH", "ruleGroup": "MATCH", "severity": "BLOCK"},
        {"ruleId": "AP.MATCH.PRICE_MISMATCH", "ruleGroup": "MATCH", "severity": "BLOCK"},
        {"ruleId": "AP.TAX.CODE_SUGGESTED", "ruleGroup": "TAX", "severity": "WARN"},
        {"ruleId": "AP.BUDGET.EXCEEDED", "ruleGroup": "BUDGET", "severity": "BLOCK"},
        {"ruleId": "AP.VENDOR.NOT_QUALIFIED", "ruleGroup": "VENDOR", "severity": "BLOCK"},
        {"ruleId": "AP.MATCH.QTY_MISMATCH_MINOR", "ruleGroup": "MATCH", "severity": "INFO"},
    ],
    "operations": [
        {"name": "ap.invoice.checkValidation", "kind": "read", "irreversible": False},
    ],
}

loader.live_metadata = lambda: FAKE_LIVE  # 模拟存量元数据可达

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


# 1) 实体清单
r, layer = tools.tool_metadata_entities({}, None)
check("entities", len(r["entities"]) == 6 and r["liveMetadata"]["available"], f"n={len(r['entities'])}")

# 2) 字段（实体名 + 中文术语）
r, _ = tools.tool_metadata_fields({"entity": "Invoice"}, None)
check("fields:live", r["fieldCount"] == 4, f"n={r['fieldCount']}")
r2, _ = tools.tool_metadata_fields({"entity": "发票"}, None)
check("fields:term", r2["entity"] == "Invoice", r2["entity"])
r3, _ = tools.tool_metadata_fields({"entity": "Invoice"}, None)
check("fields:derived", any(d["name"] == "accrual_flag" for d in r3["derivedFields"]))
try:
    tools.tool_metadata_fields({"entity": "Nope"}, None)
    check("fields:unknown", False, "应抛 ToolError")
except tools.ToolError:
    check("fields:unknown", True)

# 3) 指标：双租阈值 + 来源取证 + 无租回退
r, layer = tools.tool_metric_get({"metric": "large_risk_amount"}, "T-EAST")
check("metric:east", r["caliber"]["threshold"] == 500000 and layer == "tenant",
      f"thr={r['caliber']['threshold']} layer={layer} src={r['caliber']['thresholdSource'][:20]}")
r, layer = tools.tool_metric_get({"metric": "large_risk_amount"}, "T-UNI")
check("metric:uni", r["caliber"]["threshold"] == 5000000 and layer == "tenant",
      f"thr={r['caliber']['threshold']}")
r, layer = tools.tool_metric_get({"metric": "large_risk_amount"}, None)
check("metric:std", r["caliber"]["threshold"] == 500000 and layer == "standard")
r, layer = tools.tool_metric_get({"metric": "net_payable"}, "T-EAST")
check("metric:net-east", r["caliber"]["includesAccrual"] is False and layer == "tenant",
      r["caliber"]["formula"])
r, layer = tools.tool_metric_get({"metric": "net_payable"}, "T-UNI")
check("metric:net-uni", r["caliber"]["includesAccrual"] is True and layer == "tenant",
      r["caliber"]["formula"])
try:
    tools.tool_metric_get({"metric": "nope"}, None)
    check("metric:unknown", False)
except tools.ToolError:
    check("metric:unknown", True)

# 4) 术语：双租同题不同答 + 无租提示
r, layer = tools.tool_term_translate({"term": "进货单"}, "T-EAST")
check("term:east", r["semantic"] == "purchase_order" and layer == "tenant", str(r.get("semantic")))
r, layer = tools.tool_term_translate({"term": "进货单"}, "T-UNI")
check("term:uni", r["semantic"] == "goods_receipt" and layer == "tenant", str(r.get("semantic")))
r, layer = tools.tool_term_translate({"term": "进货单"}, None)
check("term:no-tenant", r["matched"] is False and len(r["tenantCalibers"]) == 2,
      f"calibers={len(r['tenantCalibers'])}")
r, layer = tools.tool_term_translate({"term": "发票"}, "T-EAST")
check("term:standard", r["entity"] == "Invoice" and layer == "standard")

# 5) 问题匹配：精确 + 改述
r, _ = tools.tool_task_match({"question": "这张发票为什么被阻断？"}, None)
check("task:exact", r["matched"] and r["question"]["id"] == "Q01", str(r["question"]["id"]))
r, _ = tools.tool_task_match({"question": "为什么这张发票会被拦下来"}, None)
check("task:fuzzy", r["matched"] and r["question"]["id"] == "Q01",
      f"id={r['question']['id']} score={r['score']}")
r, _ = tools.tool_task_match({"question": "帮我订一张机票"}, None)
check("task:miss", r["matched"] is False, f"score={r['score']}")

# 6) 操作解释：列表 + 单个 + 未知
r, _ = tools.tool_operation_explain({}, None)
check("op:list", len(r["operations"]) == 6, f"n={len(r['operations'])}")
r, _ = tools.tool_operation_explain({"operation": "ap.invoice.applyTaxCode"}, None)
check("op:apply", r["irreversible"] is True and r["sodGroup"] == "ap-tax-write"
      and "GW.APPROVAL_REQUIRED" in str(r["approvalPolicy"]))
r, _ = tools.tool_operation_explain({"operation": "ap.payment.execute"}, None)
check("op:payment", r["sodGroup"] == "ap-payment" and r["irreversible"] is True)
try:
    tools.tool_operation_explain({"operation": "nope"}, None)
    check("op:unknown", False)
except tools.ToolError:
    check("op:unknown", True)

# 7) 漂移：两条预埋漂移必须检出
r, _ = tools.tool_drift_status({}, None)
kinds = [(d["kind"], d["semanticRef"]) for d in r["items"]]
check("drift:count", r["drifted"] and r["counts"]["drifts"] == 2, str(kinds))
check("drift:field", ("FIELD_DRIFT", "Invoice.accrual_flag") in kinds
      and any(d.get("live") == "is_accrual" for d in r["items"] if d["kind"] == "FIELD_DRIFT"))
check("drift:rule", ("RULE_DRIFT", "AP.TAX.RATE_CHECK") in kinds)

# 8) 信封：main.py 包装逻辑（不启服务器，直接调 handler 走 _meta 路径）
r, layer = tools.tool_metric_get({"metric": "large_risk_amount"}, "T-UNI")
check("envelope:meta", layer == "tenant" and loader.semantic_version() == "ap-sem-1.0.0")

print()
print("RESULT:", "ALL_PASS" if not failures else f"FAILED: {failures}")
sys.exit(0 if not failures else 1)
