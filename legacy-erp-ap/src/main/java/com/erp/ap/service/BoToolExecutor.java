package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * BO 工具执行器：BO API（REST）与 MCP（tools/call）共用的分发核心。
 * 工具名/参数契约来自 boapi-spec/bo-ap.yaml（构建期 manifest）。
 */
@Service
@RequiredArgsConstructor
public class BoToolExecutor {

    private final ValidationService validationService;
    private final InvoiceQueryService invoiceQueryService;
    private final ProcurementQueryService procurementQueryService;
    private final TaxCodeService taxCodeService;
    private final PaymentService paymentService;

    public Map<String, Object> execute(String toolName, Map<String, Object> args,
                                       String approver, String approvalRef) {
        return switch (toolName) {
            case "ap.invoice.checkValidation" -> validationService.checkValidation(
                    str(args.get("invoiceNo")), strList(args.get("ruleGroups")));
            case "ap.invoice.listBlocked" -> invoiceQueryService.listBlocked(
                    strOrNull(args.get("cursor")),
                    args.get("pageSize") == null ? null : num(args.get("pageSize")).intValue(),
                    args.get("minAmountCny") == null ? null : num(args.get("minAmountCny")));
            case "ap.invoice.getMatchDetail" -> invoiceQueryService.matchDetail(str(args.get("invoiceNo")));
            case "proc.po.getDetail" -> procurementQueryService.poDetail(str(args.get("poNo")));
            case "proc.gr.listForPo" -> procurementQueryService.grListForPo(str(args.get("poNo")));
            case "ap.balance.query" -> invoiceQueryService.balanceQuery(
                    str(args.get("metric")), strOrNull(args.get("period")), strOrNull(args.get("scope")));
            case "ap.invoice.applyTaxCode" -> taxCodeService.applyTaxCode(
                    str(args.get("invoiceNo")), str(args.get("taxCode")), str(args.get("reason")),
                    str(args.get("accountPeriod")), approver, approvalRef);
            case "ap.payment.execute" -> paymentService.execute(
                    str(args.get("paymentOrderNo")), str(args.get("invoiceNo")), num(args.get("amountCny")));
            default -> throw BoApiException.validation("AP.VALIDATION_ERROR", "未知工具：" + toolName);
        };
    }

    private static String str(Object o) {
        if (o == null) {
            throw BoApiException.validation("AP.VALIDATION_ERROR", "缺少必填参数");
        }
        return String.valueOf(o);
    }

    private static String strOrNull(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private static List<String> strList(Object o) {
        if (o == null) {
            return List.of();
        }
        if (o instanceof List<?> list) {
            return list.stream().map(String::valueOf).toList();
        }
        // 逗号分隔字符串（REST query 场景）
        return List.of(String.valueOf(o).split(","));
    }

    private static BigDecimal num(Object o) {
        if (o instanceof Number n) {
            return new BigDecimal(n.toString());
        }
        return new BigDecimal(String.valueOf(o));
    }
}
