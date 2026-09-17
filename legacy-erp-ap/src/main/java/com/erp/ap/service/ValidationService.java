package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.*;
import com.erp.ap.repo.*;
import com.erp.ap.rules.Rule;
import com.erp.ap.rules.RuleEngine;
import com.erp.ap.rules.RuleGroup;
import com.erp.ap.security.AuthContext;
import com.erp.ap.security.PermissionService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.*;

/**
 * 发票校验编排：权限裁剪规则组 + completeness 披露 + 阻断事件 outbox。
 */
@Service
@RequiredArgsConstructor
public class ValidationService {

    private final InvoiceRepo invoiceRepo;
    private final InvoiceLineRepo invoiceLineRepo;
    private final SupplierRepo supplierRepo;
    private final TaxCodeConfigRepo taxCodeConfigRepo;
    private final BudgetOccupancyRepo budgetOccupancyRepo;
    private final PoLineRepo poLineRepo;
    private final GrLineRepo grLineRepo;
    private final RuleEngine ruleEngine;
    private final PermissionService permissionService;
    private final OutboxService outboxService;

    public Map<String, Object> checkValidation(String invoiceNo, List<String> ruleGroups) {
        Invoice invoice = loadInvoiceInScope(invoiceNo);
        if ("DRAFT".equals(invoice.getStatus())) {
            throw BoApiException.stateConflict("AP.INVOICE_IN_DRAFT",
                    "发票 " + invoiceNo + " 为草稿状态，校验前需先提交");
        }
        if ("VOIDED".equals(invoice.getStatus())) {
            // 作废单据按不可见处理（不泄露存在性）
            throw BoApiException.notFound("AP.INVOICE_NOT_FOUND", "单据不存在或不在您的数据权限范围内");
        }

        List<InvoiceLine> lines = invoiceLineRepo.findByInvoiceIdOrderByLineNoAsc(invoice.getId());
        Rule.RuleContext ctx = buildContext(invoice);

        List<RuleGroup> requested = parseGroups(ruleGroups);
        // ★ 组级权限判定：用户对组内全部权限码且组织范围覆盖发票组织才可执行
        var evaluation = ruleEngine.evaluate(invoice, lines, ctx, requested, group -> groupAllowed(group, invoice.getOrg()));

        boolean full = evaluation.skippedGroups().isEmpty();
        Map<String, Object> completeness = new LinkedHashMap<>();
        completeness.put("full", full);
        completeness.put("skippedRuleGroups", evaluation.skippedGroups());
        completeness.put("reason", full ? null
                : "权限不足（" + describeMissing(evaluation.skippedGroups()) + "），相关规则组未执行");
        completeness.put("note", full ? null : "结果基于可见规则组，不代表完整校验结论");

        String overall = RuleEngine.overallResultOf(evaluation.findings());

        // 阻断事件（幂等 outbox，仅首次评估发布）
        if ("BLOCKED".equals(overall)) {
            outboxService.publishInvoiceBlocked(invoice, evaluation.findings());
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("invoiceNo", invoice.getInvoiceNo());
        Map<String, Object> summary = new LinkedHashMap<>();
        Supplier supplier = supplierRepo.findById(invoice.getSupplierId()).orElse(null);
        summary.put("supplier", supplier == null ? null : supplier.getName());
        summary.put("amountCny", invoice.getAmountCny());
        summary.put("status", invoice.getStatus());
        result.put("invoiceSummary", summary);
        result.put("overallResult", overall);
        result.put("completeness", completeness);
        result.put("findings", evaluation.findings());
        result.put("evaluatedAt", OffsetDateTime.now().toString());
        result.put("ruleSetVersion", RuleEngine.RULESET_VERSION);
        return result;
    }

    // ---------- 内部 ----------

    public Invoice loadInvoiceInScope(String invoiceNo) {
        permissionService.require("ap.invoice.read");
        Invoice invoice = invoiceRepo.findByInvoiceNo(invoiceNo)
                .orElseThrow(() -> BoApiException.notFound("AP.INVOICE_NOT_FOUND",
                        "单据不存在或不在您的数据权限范围内"));
        // 租户维度越界同样按未找到处理（不泄露存在性）—— 显式判定，不依赖会话级过滤器
        String tid = AuthContext.get().getTenantId();
        if (tid == null || tid.isBlank() || !tid.equals(invoice.getTenantId())) {
            throw BoApiException.notFound("AP.INVOICE_NOT_FOUND", "单据不存在或不在您的数据权限范围内");
        }
        // 组织维度越界同样按未找到处理（不泄露存在性）
        if (AuthContext.get().getAuthType() != AuthContext.AuthType.APPID) {
            permissionService.requireCovers("ap.invoice.read", invoice.getOrg());
        }
        return invoice;
    }

    /** 写操作权限：ap.taxcode.write 且组织范围覆盖发票组织。 */
    public void requireWriteOn(Invoice invoice) {
        permissionService.requireCovers("ap.taxcode.write", invoice.getOrg());
    }

    private boolean groupAllowed(RuleGroup group, String invoiceOrg) {
        List<String> required = RuleEngine.GROUP_PERMISSIONS.get(group);
        for (String code : required) {
            if (!AuthContext.get().hasPermission(code)) {
                return false;
            }
            var scope = AuthContext.get().scopeOf(code);
            if (scope != null && !scope.covers(invoiceOrg)) {
                return false;
            }
        }
        return true;
    }

    private String describeMissing(List<String> skipped) {
        List<String> missing = new ArrayList<>();
        for (String g : skipped) {
            RuleGroup group = RuleGroup.valueOf(g);
            for (String code : RuleEngine.GROUP_PERMISSIONS.get(group)) {
                if (!AuthContext.get().hasPermission(code)) {
                    missing.add(code);
                }
            }
        }
        return String.join("、", missing);
    }

    private List<RuleGroup> parseGroups(List<String> groups) {
        if (groups == null || groups.isEmpty()) {
            return List.of();
        }
        List<RuleGroup> out = new ArrayList<>();
        for (String g : groups) {
            try {
                out.add(RuleGroup.valueOf(g));
            } catch (IllegalArgumentException e) {
                throw BoApiException.validation("AP.VALIDATION_ERROR", "未知规则组：" + g);
            }
        }
        return out;
    }

    private Rule.RuleContext buildContext(Invoice invoice) {
        Supplier supplier = invoice.getSupplierId() == null ? null
                : supplierRepo.findById(invoice.getSupplierId()).orElse(null);
        TaxCodeConfig taxConfig = supplier == null ? null
                : taxCodeConfigRepo.findByTenantIdAndRegion(AuthContext.get().getTenantId(), supplier.getRegion()).orElse(null);
        BudgetOccupancy budget = budgetOccupancyRepo
                .findByOrgAndPeriod(invoice.getOrg(), invoice.getPeriod()).orElse(null);

        Map<Long, BigDecimal> grQty = new HashMap<>();
        Map<Long, BigDecimal> poPrice = new HashMap<>();
        if (invoice.getGrId() != null) {
            for (GrLine gl : grLineRepo.findByGrIdOrderByIdAsc(invoice.getGrId())) {
                grQty.put(gl.getId(), gl.getQty());
            }
        }
        if (invoice.getPoId() != null) {
            for (PoLine pl : poLineRepo.findByPoIdOrderByLineNoAsc(invoice.getPoId())) {
                poPrice.put(pl.getId(), pl.getUnitPrice());
            }
        }

        final Supplier fSupplier = supplier;
        final TaxCodeConfig fTax = taxConfig;
        final BudgetOccupancy fBudget = budget;
        return new Rule.RuleContext() {
            @Override public String supplierRegion() {
                return fSupplier == null ? null : fSupplier.getRegion();
            }
            @Override public boolean supplierQualified() {
                return fSupplier != null && Boolean.TRUE.equals(fSupplier.getQualified());
            }
            @Override public String commonTaxCode() {
                return fTax == null ? null : fTax.getCommonTaxCode();
            }
            @Override public BigDecimal budgetRemaining() {
                return fBudget == null ? null : fBudget.getBudgetAmount().subtract(fBudget.getOccupiedAmount());
            }
            @Override public BigDecimal grQtyOf(Long grLineId) {
                return grQty.get(grLineId);
            }
            @Override public BigDecimal poPriceOf(Long poLineId) {
                return poPrice.get(poLineId);
            }
        };
    }
}
