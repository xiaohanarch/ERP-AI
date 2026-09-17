package com.erp.ap.domain;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.Filter;

import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "erp_user")
@Filter(name = "tenant", condition = "tenant_id = :tid")
@Getter
@Setter
public class ErpUser {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String username;
    private String passwordHash;
    private String displayName;
    private String tenantId;
    private String org;
    private String title;

    /** 角色关联（user_role 集合表）。 */
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "user_role", joinColumns = @JoinColumn(name = "user_id"))
    @Column(name = "role_id")
    private List<Long> roleIds = new ArrayList<>();
}
