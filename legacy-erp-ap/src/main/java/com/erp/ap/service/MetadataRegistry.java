package com.erp.ap.service;

import com.erp.ap.rules.RuleEngine;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 元数据注册表：实体/字段/枚举/规则清单 —— 语义层「投影段」实时取数源，
 * 也是漂移检测（drift_check）的比对基准（元数据现状）。
 *
 * ★ 预埋漂移基准：本注册表是唯一事实。语义文件增量段若引用了此处
 *   不存在的字段（如 accrual_flag）或不存在的规则（如 AP.TAX.RATE_CHECK），
 *   drift_check 必须报出。
 */
@Service
public class MetadataRegistry {

    public Map<String, Object> full() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("appid", "erp-ap");
        out.put("domain", "AP");
        out.put("ruleSetVersion", RuleEngine.RULESET_VERSION);
        out.put("seedVersion", "ap-seed-1.0.0");
        out.put("entities", entities());
        out.put("enums", enums());
        out.put("rules", ruleCatalogStatic());
        out.put("operations", operations());
        return out;
    }

    private Map<String, Object> entities() {
        Map<String, Object> entities = new LinkedHashMap<>();
        entities.put("Invoice", entity("发票",
                field("invoice_no", "string", "发票号"),
                field("supplier_id", "long", "供应商ID"),
                field("org", "string", "组织"),
                field("company", "string", "公司"),
                field("amount_cny", "decimal", "含税金额(元)"),
                field("tax_code", "string", "税码"),
                field("status", "enum:InvoiceStatus", "单据状态"),
                field("validation_status", "enum:ValidationStatus", "校验状态"),
                field("is_accrual", "boolean", "是否暂估"),
                field("period", "string", "会计期间"),
                field("paid_cny", "decimal", "已付金额(元)")));
        entities.put("PurchaseOrder", entity("采购订单",
                field("po_no", "string", "PO号"),
                field("supplier_id", "long", "供应商ID"),
                field("org", "string", "组织"),
                field("status", "string", "状态")));
        entities.put("PurchaseOrderLine", entity("采购订单行",
                field("po_id", "long", "PO ID"),
                field("item", "string", "物料"),
                field("qty", "decimal", "数量"),
                field("unit_price", "decimal", "单价")));
        entities.put("GoodsReceipt", entity("收货单",
                field("gr_no", "string", "GR号"),
                field("po_id", "long", "PO ID"),
                field("org", "string", "组织")));
        entities.put("GoodsReceiptLine", entity("收货单行",
                field("gr_id", "long", "GR ID"),
                field("po_line_id", "long", "PO行ID"),
                field("item", "string", "物料"),
                field("qty", "decimal", "数量")));
        entities.put("Supplier", entity("供应商",
                field("code", "string", "编码"),
                field("name", "string", "名称"),
                field("region", "string", "所在地"),
                field("qualified", "boolean", "是否过准入")));
        entities.put("BudgetOccupancy", entity("预算占用",
                field("org", "string", "组织"),
                field("period", "string", "期间"),
                field("budget_amount", "decimal", "预算总额"),
                field("occupied_amount", "decimal", "已占用金额")));
        entities.put("InvoiceTaxChange", entity("税码变更记录",
                field("invoice_no", "string", "发票号"),
                field("previous_tax_code", "string", "原税码"),
                field("new_tax_code", "string", "新税码"),
                field("requested_by", "string", "发起人"),
                field("decided_by", "string", "审批人"),
                field("approval_ref", "string", "审批单号")));
        return entities;
    }

    private Map<String, Object> enums() {
        Map<String, Object> enums = new LinkedHashMap<>();
        enums.put("InvoiceStatus", List.of("DRAFT", "POSTED", "VOIDED"));
        enums.put("ValidationStatus", List.of("PASSED", "WARNED", "BLOCKED", "UNEVALUATED"));
        enums.put("Severity", List.of("BLOCK", "WARN", "INFO"));
        enums.put("RuleGroup", List.of("MATCH", "TAX", "BUDGET", "VENDOR"));
        return enums;
    }

    /** 与 RuleEngine 实际注册的规则一一对应（静态口径，供漂移比对）。 */
    private List<Map<String, Object>> ruleCatalogStatic() {
        return List.of(
                rule("AP.MATCH.QTY_MISMATCH", "MATCH", "BLOCK"),
                rule("AP.MATCH.PRICE_MISMATCH", "MATCH", "BLOCK"),
                rule("AP.MATCH.QTY_MISMATCH_MINOR", "MATCH", "INFO"),
                rule("AP.TAX.CODE_SUGGESTED", "TAX", "WARN"),
                rule("AP.BUDGET.EXCEEDED", "BUDGET", "BLOCK"),
                rule("AP.VENDOR.NOT_QUALIFIED", "VENDOR", "BLOCK"));
    }

    private List<Map<String, Object>> operations() {
        return List.of(
                Map.of("name", "ap.invoice.checkValidation", "kind", "read", "irreversible", false),
                Map.of("name", "ap.invoice.listBlocked", "kind", "read", "irreversible", false),
                Map.of("name", "ap.invoice.getMatchDetail", "kind", "read", "irreversible", false),
                Map.of("name", "ap.balance.query", "kind", "read", "irreversible", false),
                Map.of("name", "ap.invoice.applyTaxCode", "kind", "write", "irreversible", true),
                Map.of("name", "ap.payment.execute", "kind", "write", "irreversible", true));
    }

    // ---------- 构建辅助 ----------

    private Map<String, Object> entity(String label, Map<String, Object>... fields) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("label", label);
        m.put("fields", List.of(fields));
        return m;
    }

    private Map<String, Object> field(String name, String type, String label) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", name);
        m.put("type", type);
        m.put("label", label);
        return m;
    }

    private Map<String, Object> rule(String id, String group, String severity) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ruleId", id);
        m.put("ruleGroup", group);
        m.put("severity", severity);
        return m;
    }
}
