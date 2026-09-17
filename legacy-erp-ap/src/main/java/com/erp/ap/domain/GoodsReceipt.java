package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.time.LocalDate;

@Entity
@Table(name = "goods_receipt")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class GoodsReceipt {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String grNo;
    private Long poId;
    private String org;
    private String tenantId;
    private LocalDate receiptDate;
}
