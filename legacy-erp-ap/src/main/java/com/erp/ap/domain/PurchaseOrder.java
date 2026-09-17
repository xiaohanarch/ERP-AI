package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.time.LocalDate;

@Entity
@Table(name = "purchase_order")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class PurchaseOrder {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String poNo;
    private Long supplierId;
    private String org;
    private String tenantId;
    private String status;
    private LocalDate orderDate;
}
