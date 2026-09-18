package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.IdempotencyRecord;
import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceTaxChange;
import com.erp.ap.repo.IdempotencyRepo;
import com.erp.ap.repo.InvoiceTaxChangeRepo;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 税码建议落库（写路径标的）：
 *  - 业务幂等键 = 发票号 + 税码 + 会计期间（唯一约束，与变更同事务）；
 *  - 审批人/审批单号由网关经请求头透传（X-BO-Approver / X-BO-Approval-Ref）留痕。
 */
@Service
@RequiredArgsConstructor
public class TaxCodeService {

    private final ValidationService validationService;
    private final IdempotencyRepo idempotencyRepo;
    private final InvoiceTaxChangeRepo taxChangeRepo;
    private final ObjectMapper objectMapper;

    @Transactional
    public Map<String, Object> applyTaxCode(String invoiceNo, String taxCode, String reason,
                                            String accountPeriod, String approver, String approvalRef) {
        Invoice invoice = validationService.loadInvoiceInScope(invoiceNo);
        // 写权限独立校验（组织范围覆盖）
        validationService.requireWriteOn(invoice);
        if ("DRAFT".equals(invoice.getStatus())) {
            throw BoApiException.stateConflict("AP.INVOICE_IN_DRAFT",
                    "发票 " + invoiceNo + " 为草稿状态，不能应用税码");
        }
        if ("VOIDED".equals(invoice.getStatus())) {
            throw BoApiException.notFound("AP.INVOICE_NOT_FOUND", "单据不存在或不在您的数据权限范围内");
        }

        String businessKey = invoiceNo + "|" + taxCode + "|" + accountPeriod;
        // 参数哈希只覆盖操作性参数（税码+会计期间）：reason 为人读说明文本，live 模型每次措辞不同，
        // 不应参与幂等判定 —— 同业务键重发一律重放首次结果（与规格 x-bo-idempotency 语义一致）
        String paramsHash = sha256(taxCode + "|" + accountPeriod);

        // 业务幂等：COMPLETED -> 返回首次结果；参数不一致 -> 冲突
        IdempotencyRecord existing = idempotencyRepo.findByBusinessKey(businessKey).orElse(null);
        if (existing != null) {
            if (existing.getParamsHash().equals(paramsHash)) {
                return replayResult(existing);
            }
            throw BoApiException.stateConflict("AP.IDEMPOTENCY_CONFLICT",
                    "幂等键冲突：同业务键已存在不同参数的记录（键=" + businessKey + "）");
        }

        String previousTaxCode = invoice.getTaxCode();
        invoice.setTaxCode(taxCode);
        InvoiceTaxChange change = new InvoiceTaxChange();
        change.setTenantId(invoice.getTenantId());
        change.setInvoiceNo(invoiceNo);
        change.setPreviousTaxCode(previousTaxCode);
        change.setNewTaxCode(taxCode);
        change.setReason(reason);
        change.setAccountPeriod(accountPeriod);
        change.setRequestedBy(currentRequester());
        change.setDecidedBy(approver);
        change.setApprovalRef(approvalRef);
        change.setAppliedAt(OffsetDateTime.now());
        taxChangeRepo.save(change);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("invoiceNo", invoiceNo);
        result.put("previousTaxCode", previousTaxCode);
        result.put("newTaxCode", taxCode);
        result.put("changeId", "TC-" + change.getId());
        result.put("decidedBy", approver);
        result.put("approvalRef", approvalRef);
        result.put("appliedAt", change.getAppliedAt().toString());
        result.put("idempotentReplay", false);

        IdempotencyRecord record = new IdempotencyRecord();
        record.setTenantId(invoice.getTenantId());
        record.setBusinessKey(businessKey);
        record.setToolName("ap.invoice.applyTaxCode");
        record.setParamsHash(paramsHash);
        record.setStatus("COMPLETED");
        record.setResultJson(toJson(result));
        record.setCreatedAt(OffsetDateTime.now());
        try {
            idempotencyRepo.saveAndFlush(record);
        } catch (DataIntegrityViolationException e) {
            // 并发同键：回读按幂等处理
            IdempotencyRecord winner = idempotencyRepo.findByBusinessKey(businessKey).orElse(null);
            if (winner != null && winner.getParamsHash().equals(paramsHash)) {
                return replayResult(winner);
            }
            throw BoApiException.stateConflict("AP.IDEMPOTENCY_CONFLICT", "幂等键冲突（并发写入）");
        }
        return result;
    }

    private Map<String, Object> replayResult(IdempotencyRecord record) {
        try {
            Map<String, Object> result = objectMapper.readValue(record.getResultJson(), Map.class);
            result.put("idempotentReplay", true);
            return result;
        } catch (Exception e) {
            throw new IllegalStateException("幂等记录损坏: " + record.getBusinessKey(), e);
        }
    }

    private String currentRequester() {
        var ctx = com.erp.ap.security.AuthContext.get();
        return "u-" + ctx.getUsername();
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private String toJson(Map<String, Object> value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return "{}";
        }
    }
}
