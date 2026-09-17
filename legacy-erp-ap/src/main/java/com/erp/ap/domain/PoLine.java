package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Entity
@Table(name = "po_line")
@Getter
@Setter
public class PoLine {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private Long poId;
    private Integer lineNo;
    private String item;
    private BigDecimal qty;
    private BigDecimal unitPrice;
}
