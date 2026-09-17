package com.erp.ap.boapi;

import com.erp.ap.service.BoToolExecutor;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * BO API（REST 直连形态，与 MCP 同一执行器）。
 * 认证：仅接受网关铸造的 T3（见 AuthFilter）；每个端点校验工具 scope。
 */
@RestController
@RequestMapping("/boapi")
@RequiredArgsConstructor
public class BoApiController {

    private final BoToolExecutor executor;

    private void requireTool(String toolName) {
        var ctx = com.erp.ap.security.AuthContext.get();
        if (ctx.getToolScope() != null && !toolName.equals(ctx.getToolScope())) {
            throw BoApiException.permissionDenied("AP.PERMISSION_DENIED",
                    "T3 scope 不包含工具 " + toolName + "（scope=" + ctx.getToolScope() + "）");
        }
    }

    @GetMapping("/invoices/{invoiceNo}/check-validation")
    public Map<String, Object> checkValidation(@PathVariable String invoiceNo,
                                               @RequestParam(required = false) List<String> ruleGroups) {
        requireTool("ap.invoice.checkValidation");
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("invoiceNo", invoiceNo);
        if (ruleGroups != null && !ruleGroups.isEmpty()) {
            args.put("ruleGroups", ruleGroups);
        }
        return executor.execute("ap.invoice.checkValidation", args, null, null);
    }

    @GetMapping("/invoices/blocked")
    public Map<String, Object> listBlocked(@RequestParam(required = false) String cursor,
                                           @RequestParam(required = false) Integer pageSize,
                                           @RequestParam(required = false) BigDecimal minAmountCny) {
        requireTool("ap.invoice.listBlocked");
        Map<String, Object> args = new LinkedHashMap<>();
        if (cursor != null) args.put("cursor", cursor);
        if (pageSize != null) args.put("pageSize", pageSize);
        if (minAmountCny != null) args.put("minAmountCny", minAmountCny);
        return executor.execute("ap.invoice.listBlocked", args, null, null);
    }

    @GetMapping("/invoices/{invoiceNo}/match-detail")
    public Map<String, Object> matchDetail(@PathVariable String invoiceNo) {
        requireTool("ap.invoice.getMatchDetail");
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("invoiceNo", invoiceNo);
        return executor.execute("ap.invoice.getMatchDetail", args, null, null);
    }

    @GetMapping("/balance/query")
    public Map<String, Object> balanceQuery(@RequestParam String metric,
                                            @RequestParam(required = false) String period,
                                            @RequestParam(required = false) String scope) {
        requireTool("ap.balance.query");
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("metric", metric);
        if (period != null) args.put("period", period);
        if (scope != null) args.put("scope", scope);
        return executor.execute("ap.balance.query", args, null, null);
    }

    @PostMapping("/invoices/{invoiceNo}/tax-code")
    public Map<String, Object> applyTaxCode(@PathVariable String invoiceNo,
                                            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
                                            @RequestHeader(value = "X-BO-Approver", required = false) String approver,
                                            @RequestHeader(value = "X-BO-Approval-Ref", required = false) String approvalRef,
                                            @RequestBody Map<String, Object> body) {
        requireTool("ap.invoice.applyTaxCode");
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw BoApiException.validation("AP.VALIDATION_ERROR", "缺少 Idempotency-Key 请求头");
        }
        Map<String, Object> args = new LinkedHashMap<>(body);
        args.put("invoiceNo", invoiceNo);
        args.put("idempotencyKey", idempotencyKey);
        return executor.execute("ap.invoice.applyTaxCode", args, approver, approvalRef);
    }

    @PostMapping("/payments/execute")
    public Map<String, Object> paymentExecute(@RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
                                              @RequestBody Map<String, Object> body) {
        requireTool("ap.payment.execute");
        Map<String, Object> args = new LinkedHashMap<>(body);
        if (idempotencyKey != null) {
            args.put("idempotencyKey", idempotencyKey);
        }
        return executor.execute("ap.payment.execute", args, null, null);
    }
}
