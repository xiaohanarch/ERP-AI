package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/** 预算占用超支（BLOCK）：发票金额 > 当前组织+期间剩余预算。 */
@Component
public class BudgetExceededRule implements Rule {

    public static final String ID = "AP.BUDGET.EXCEEDED";

    @Override
    public String ruleId() {
        return ID;
    }

    @Override
    public RuleGroup group() {
        return RuleGroup.BUDGET;
    }

    @Override
    public List<Finding> evaluate(Invoice invoice, List<InvoiceLine> lines, RuleContext ctx) {
        java.math.BigDecimal remaining = ctx.budgetRemaining();
        if (remaining == null) {
            return List.of();
        }
        if (invoice.getAmountCny().compareTo(remaining) > 0) {
            return List.of(new Finding(ID, RuleGroup.BUDGET, Severity.BLOCK,
                    "发票金额 " + invoice.getAmountCny() + " 超出组织 " + invoice.getOrg()
                            + " 期间 " + invoice.getPeriod() + " 剩余预算 " + remaining,
                    "budget_occupancy(" + invoice.getOrg() + "," + invoice.getPeriod() + ")",
                    Map.of("exceed_amount", invoice.getAmountCny().subtract(remaining),
                            "budget_remaining", remaining),
                    "追加预算或拆分发票跨期入账", List.of()));
        }
        return List.of();
    }
}
