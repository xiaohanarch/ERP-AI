package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.time.OffsetDateTime;

/**
 * 业务幂等记录（业务键唯一约束，与业务变更同事务提交）。
 * 键 = 发票号 + 税码 + 会计期间。
 */
@Entity
@Table(name = "idempotency_record")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class IdempotencyRecord {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String tenantId;
    @Column(unique = true)
    private String businessKey;
    private String toolName;
    private String paramsHash;
    private String status;     // COMPLETED / IN_PROGRESS
    private String resultJson;
    private OffsetDateTime createdAt;
}
