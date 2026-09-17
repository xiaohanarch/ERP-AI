package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 数量差异在容差内（INFO，不阻断）：收货数量 - 发票数量 ∈ (0, 2]。 */
@Component
public class QtyMinorRule implements Rule {

    public static final String ID = "AP.MATCH.QTY_MISMATCH_MINOR";
    public static final BigDecimal TOLERANCE = new BigDecimal("2");

    @Override
    public String ruleId() {
        return ID;
    }

    @Override
    public RuleGroup group() {
        return RuleGroup.MATCH;
    }

    @Override
    public Severity severity() {
        return Severity.INFO;
    }

    @Override
    public List<Finding> evaluate(Invoice invoice, List<InvoiceLine> lines, RuleContext ctx) {
        List<Finding> out = new ArrayList<>();
        for (InvoiceLine line : lines) {
            if (line.getGrLineId() == null) {
                continue;
            }
            BigDecimal grQty = ctx.grQtyOf(line.getGrLineId());
            if (grQty != null) {
                BigDecimal diff = grQty.subtract(line.getQty());
                if (diff.signum() > 0 && diff.compareTo(TOLERANCE) <= 0) {
                    out.add(new Finding(ID, RuleGroup.MATCH, Severity.INFO,
                            "第 " + line.getLineNo() + " 行 [" + line.getItem() + "] 收货数量 " + grQty
                                    + " 略高于发票数量 " + line.getQty() + "（差异 " + diff + " ≤ 容差 " + TOLERANCE + "），仅提示",
                            "invoice_line#" + line.getLineNo(),
                            Map.of("qty_diff", diff),
                            null, List.of()));
                }
            }
        }
        return out;
    }
}
