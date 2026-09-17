package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Entity
@Table(name = "invoice")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class Invoice {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String invoiceNo;
    private Long supplierId;
    private Long poId;
    private Long grId;
    private String org;
    private String company;
    private String tenantId;
    private BigDecimal amountCny;
    private String taxCode;
    private String status;            // DRAFT / POSTED / VOIDED
    private String validationStatus;  // PASSED / WARNED / BLOCKED / UNEVALUATED
    private Boolean isAccrual;
    private String period;
    private BigDecimal paidCny;
    private OffsetDateTime createdAt;
}
