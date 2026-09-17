package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.time.OffsetDateTime;

/** 税码变更留痕（谁申请、谁批准、依据与审批单号）。 */
@Entity
@Table(name = "invoice_tax_change")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class InvoiceTaxChange {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String tenantId;
    private String invoiceNo;
    private String previousTaxCode;
    private String newTaxCode;
    private String reason;
    private String accountPeriod;
    private String requestedBy;
    private String decidedBy;
    private String approvalRef;
    private OffsetDateTime appliedAt;
}
