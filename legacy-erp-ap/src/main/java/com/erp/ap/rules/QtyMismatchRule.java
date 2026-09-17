package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 发票数量 > 收货数量（BLOCK）。 */
@Component
public class QtyMismatchRule implements Rule {

    public static final String ID = "AP.MATCH.QTY_MISMATCH";

    @Override
    public String ruleId() {
        return ID;
    }

    @Override
    public RuleGroup group() {
        return RuleGroup.MATCH;
    }

    @Override
    public List<Finding> evaluate(Invoice invoice, List<InvoiceLine> lines, RuleContext ctx) {
        List<Finding> out = new ArrayList<>();
        for (InvoiceLine line : lines) {
            if (line.getGrLineId() == null) {
                continue;
            }
            BigDecimal grQty = ctx.grQtyOf(line.getGrLineId());
            if (grQty != null && line.getQty().compareTo(grQty) > 0) {
                BigDecimal diff = line.getQty().subtract(grQty);
                out.add(new Finding(ID, RuleGroup.MATCH, Severity.BLOCK,
                        "第 " + line.getLineNo() + " 行 [" + line.getItem() + "] 发票数量 " + line.getQty()
                                + " 大于收货数量 " + grQty + "，差异 " + diff,
                        "invoice_line#" + line.getLineNo(),
                        Map.of("qty_diff", diff),
                        "核对收货单后修正发票数量或补录收货", List.of()));
            }
        }
        return out;
    }
}
