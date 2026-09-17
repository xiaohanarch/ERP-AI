package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

@Entity
@Table(name = "tax_code_config")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class TaxCodeConfig {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String tenantId;
    private String region;
    private String commonTaxCode;
    private String note;
}
