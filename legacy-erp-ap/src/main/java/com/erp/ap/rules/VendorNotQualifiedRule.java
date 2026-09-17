package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/** 供应商未过准入（BLOCK）。 */
@Component
public class VendorNotQualifiedRule implements Rule {

    public static final String ID = "AP.VENDOR.NOT_QUALIFIED";

    @Override
    public String ruleId() {
        return ID;
    }

    @Override
    public RuleGroup group() {
        return RuleGroup.VENDOR;
    }

    @Override
    public List<Finding> evaluate(Invoice invoice, List<InvoiceLine> lines, RuleContext ctx) {
        if (Boolean.TRUE.equals(ctx.supplierQualified())) {
            return List.of();
        }
        return List.of(new Finding(ID, RuleGroup.VENDOR, Severity.BLOCK,
                "供应商未通过准入审核（region=" + ctx.supplierRegion() + "），发票不允许入账",
                "supplier#" + invoice.getSupplierId(),
                Map.of("invoice_amount", invoice.getAmountCny()),
                "联系采购完成供应商准入，或退回供应商重新开票", List.of()));
    }
}
