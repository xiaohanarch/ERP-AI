package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Entity
@Table(name = "gr_line")
@Getter
@Setter
public class GrLine {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private Long grId;
    private Long poLineId;
    private String item;
    private BigDecimal qty;
}
