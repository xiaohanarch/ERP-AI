package com.erp.ap.security;

import lombok.Data;

import java.util.Map;
import java.util.Set;

/**
 * 数据权限范围（三维：租户/公司/组织 —— 本演示租户随令牌、组织随权限码）。
 */
@Data
public class DataScope {
    private final Set<String> orgs;
    private final boolean allOrgs;

    public boolean covers(String org) {
        return allOrgs || orgs.contains(org);
    }
}
