package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 付款记录（演示环境 MOCK 执行，无真实资金动作）。 */
@Entity
@Table(name = "payment")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class Payment {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String tenantId;
    @Column(unique = true)
    private String paymentOrderNo;
    private String invoiceNo;
    private BigDecimal amountCny;
    private OffsetDateTime executedAt;
    private Boolean isMock;
}
