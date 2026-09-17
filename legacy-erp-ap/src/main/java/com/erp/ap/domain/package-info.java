/**
 * 领域实体包：全部租户敏感实体挂 Hibernate 租户过滤器（强制 WHERE tenant_id = ?）。
 */
@org.hibernate.annotations.FilterDef(
        name = "tenant",
        parameters = @org.hibernate.annotations.ParamDef(name = "tid", type = String.class)
)
package com.erp.ap.domain;
