package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;

import java.util.List;

/** 校验规则接口：每条规则声明自己的组、严重级别与执行入口。 */
public interface Rule {
    String ruleId();

    RuleGroup group();

    default Severity severity() {
        return Severity.BLOCK;
    }

    /** 执行校验，返回命中结果（未命中返回空列表）。 */
    List<Finding> evaluate(Invoice invoice, List<InvoiceLine> lines, RuleContext ctx);

    /** 规则执行上下文（主数据快查，由 ValidationService 组装）。 */
    interface RuleContext {
        String supplierRegion();

        boolean supplierQualified();

        String commonTaxCode();       // 供应商所在地常用税码（无则 null）

        java.math.BigDecimal budgetRemaining(); // 当前组织+期间的剩余预算（无预算行则 null）

        java.math.BigDecimal grQtyOf(Long grLineId);   // 收货行数量

        java.math.BigDecimal poPriceOf(Long poLineId); // 采购订单行单价
    }
}
