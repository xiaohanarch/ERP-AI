package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * 税码与供应商所在地常用税码不符（WARN）—— 税码建议规则。
 * remediation 指向 ap.invoice.applyTaxCode（写路径标的）。
 */
@Component
public class TaxCodeSuggestedRule implements Rule {

    public static final String ID = "AP.TAX.CODE_SUGGESTED";

    @Override
    public String ruleId() {
        return ID;
    }

    @Override
    public RuleGroup group() {
        return RuleGroup.TAX;
    }

    @Override
    public Severity severity() {
        return Severity.WARN;
    }

    @Override
    public List<Finding> evaluate(Invoice invoice, List<InvoiceLine> lines, RuleContext ctx) {
        String common = ctx.commonTaxCode();
        if (common == null || invoice.getTaxCode() == null || common.equals(invoice.getTaxCode())) {
            return List.of();
        }
        return List.of(new Finding(ID, RuleGroup.TAX, Severity.WARN,
                "发票税码 " + invoice.getTaxCode() + " 与供应商所在地（" + ctx.supplierRegion()
                        + "）常用税码 " + common + " 不符，建议核对税码",
                "invoice.tax_code",
                Map.of(),
                "建议将税码调整为 " + common + "（需审批后落库）",
                List.of("ap.invoice.applyTaxCode")));
    }
}
