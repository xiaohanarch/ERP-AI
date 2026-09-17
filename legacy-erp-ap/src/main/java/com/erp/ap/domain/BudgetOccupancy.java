package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.math.BigDecimal;

@Entity
@Table(name = "budget_occupancy")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class BudgetOccupancy {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String tenantId;
    private String org;
    private String period;
    private BigDecimal budgetAmount;
    private BigDecimal occupiedAmount;
}
