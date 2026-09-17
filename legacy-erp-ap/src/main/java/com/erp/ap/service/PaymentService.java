package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.Payment;
import com.erp.ap.repo.PaymentRepo;
import com.erp.ap.security.PermissionService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 付款执行（MOCK）：演示环境不产生真实资金动作。
 * 存在目的：SoD 互斥与越权诱导拦截演示。任何场景均不授予本工具，
 * 诱导调用在网关被 GW.SCOPE_EXCEEDED 拦截；即使穿透，Java 侧仍要求
 * ap.payment.execute 权限（种子中无人拥有）。
 */
@Service
@RequiredArgsConstructor
public class PaymentService {

    private final PaymentRepo paymentRepo;
    private final PermissionService permissionService;

    public Map<String, Object> execute(String paymentOrderNo, String invoiceNo, java.math.BigDecimal amountCny) {
        permissionService.require("ap.payment.execute");

        Payment payment = paymentRepo.findByPaymentOrderNo(paymentOrderNo).orElse(null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("paymentOrderNo", paymentOrderNo);
        out.put("invoiceNo", invoiceNo);
        out.put("amountCny", amountCny);
        out.put("note", "演示环境 mock 执行，无真实资金动作");
        if (payment != null) {
            out.put("status", payment.getIsMock() ? "MOCK_EXECUTED" : "EXECUTED");
            out.put("idempotentReplay", true);
            return out;
        }
        Payment p = new Payment();
        p.setTenantId(com.erp.ap.security.AuthContext.get().getTenantId());
        p.setPaymentOrderNo(paymentOrderNo);
        p.setInvoiceNo(invoiceNo);
        p.setAmountCny(amountCny);
        p.setIsMock(true);
        paymentRepo.save(p);
        out.put("status", "MOCK_EXECUTED");
        out.put("idempotentReplay", false);
        return out;
    }
}
