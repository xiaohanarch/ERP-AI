package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 发票单价 ≠ 采购订单单价（BLOCK）。 */
@Component
public class PriceMismatchRule implements Rule {

    public static final String ID = "AP.MATCH.PRICE_MISMATCH";

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
            if (line.getPoLineId() == null) {
                continue;
            }
            BigDecimal poPrice = ctx.poPriceOf(line.getPoLineId());
            if (poPrice != null && line.getUnitPrice().compareTo(poPrice) != 0) {
                BigDecimal diff = line.getUnitPrice().subtract(poPrice);
                out.add(new Finding(ID, RuleGroup.MATCH, Severity.BLOCK,
                        "第 " + line.getLineNo() + " 行 [" + line.getItem() + "] 发票单价 " + line.getUnitPrice()
                                + " 与采购订单单价 " + poPrice + " 不一致，差异 " + diff,
                        "invoice_line#" + line.getLineNo(),
                        Map.of("unit_price_diff", diff),
                        "按采购订单价格重新开票或发起价格变更流程", List.of()));
            }
        }
        return out;
    }
}
