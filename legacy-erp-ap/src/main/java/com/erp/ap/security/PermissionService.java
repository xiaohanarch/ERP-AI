package com.erp.ap.security;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.ErpUser;
import com.erp.ap.repo.ErpUserRepo;
import com.erp.ap.repo.RolePermissionRepo;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * ★ 三维数据权限服务（UI API 与 BO API 共用 —— 权限同源，页面和 AI 看到的数据范围才一致）。
 *
 * 权限码 -> DataScope（orgs 集合或 all_orgs）。T3 的 sub 即最终用户，
 * AI 侧零权限计算：判定全部发生在这里。
 */
@Service
@RequiredArgsConstructor
public class PermissionService {

    private final ErpUserRepo userRepo;
    private final RolePermissionRepo rolePermissionRepo;
    private final ObjectMapper objectMapper;

    /** 按用户名加载权限映射（用户不存在/租户不符 -> 由调用方决定 NOT_FOUND）。 */
    public Map<String, DataScope> loadPermissions(String username, String expectedTenant) {
        ErpUser user = userRepo.findByUsername(username).orElse(null);
        if (user == null) {
            throw BoApiException.notFound("AP.INVOICE_NOT_FOUND", "用户不存在");
        }
        if (expectedTenant != null && !expectedTenant.equals(user.getTenantId())) {
            throw BoApiException.permissionDenied("AP.PERMISSION_DENIED", "令牌租户与用户租户不符");
        }
        Map<String, DataScope> result = new HashMap<>();
        if (!user.getRoleIds().isEmpty()) {
            for (var rp : rolePermissionRepo.findByRoleIdIn(user.getRoleIds())) {
                result.merge(rp.getPermissionCode(), parseScope(rp.getScopeJson()), this::mergeScope);
            }
        }
        return result;
    }

    public ErpUser loadUser(String username) {
        return userRepo.findByUsername(username)
                .orElseThrow(() -> BoApiException.notFound("AP.INVOICE_NOT_FOUND", "用户不存在"));
    }

    /** 要求拥有权限码（不考虑组织维度时使用）。 */
    public void require(String code) {
        AuthContext ctx = AuthContext.get();
        if (ctx.getAuthType() == AuthContext.AuthType.APPID) {
            return; // Open API 凭据：租户级直通（历史口径）
        }
        if (!ctx.hasPermission(code)) {
            throw BoApiException.permissionDenied("AP.PERMISSION_DENIED",
                    "缺少权限码 " + code + "（用户 " + ctx.getUsername() + "）");
        }
    }

    /** 要求权限码且组织范围覆盖指定组织。 */
    public void requireCovers(String code, String org) {
        require(code);
        AuthContext ctx = AuthContext.get();
        if (ctx.getAuthType() == AuthContext.AuthType.APPID) {
            return;
        }
        DataScope scope = ctx.scopeOf(code);
        if (scope != null && !scope.covers(org)) {
            // 不泄露存在性：越界按未找到处理
            throw BoApiException.notFound("AP.INVOICE_NOT_FOUND", "单据不存在或不在您的数据权限范围内");
        }
    }

    /** 当前主体在某权限码下可见的组织集合（all_orgs 时返回 null 表示不设限）。 */
    public Set<String> accessibleOrgs(String code) {
        AuthContext ctx = AuthContext.get();
        if (ctx.getAuthType() == AuthContext.AuthType.APPID) {
            return null;
        }
        DataScope scope = ctx.scopeOf(code);
        if (scope == null) {
            throw BoApiException.permissionDenied("AP.PERMISSION_DENIED", "缺少权限码 " + code);
        }
        return scope.isAllOrgs() ? null : scope.getOrgs();
    }

    private DataScope mergeScope(DataScope a, DataScope b) {
        if (a.isAllOrgs() || b.isAllOrgs()) {
            return new DataScope(java.util.Set.of(), true);
        }
        Set<String> orgs = new HashSet<>(a.getOrgs());
        orgs.addAll(b.getOrgs());
        return new DataScope(orgs, false);
    }

    private DataScope parseScope(String scopeJson) {
        try {
            JsonNode node = objectMapper.readTree(scopeJson);
            if (node.path("all_orgs").asBoolean(false)) {
                return new DataScope(Set.of(), true);
            }
            Set<String> orgs = new HashSet<>();
            node.withArray("orgs").forEach(n -> orgs.add(n.asText()));
            return new DataScope(orgs, false);
        } catch (Exception e) {
            return new DataScope(Set.of(), false);
        }
    }
}
