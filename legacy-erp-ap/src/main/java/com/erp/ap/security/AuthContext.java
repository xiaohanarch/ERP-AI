package com.erp.ap.security;

import lombok.Getter;

import java.util.Collections;
import java.util.Map;

/**
 * 每请求认证上下文（由 AuthFilter 解析后放入 ThreadLocal）。
 *
 * authType 说明：
 *  - SESSION：ERP 页面会话（cookie）
 *  - T3     ：网关铸造的双主体令牌（sub=最终用户，scope=单工具，azp=erp-ai-action）
 *  - APPID  ：Open API 直连凭据（租户级 —— 事故口径的根源）
 */
@Getter
public class AuthContext {
    public enum AuthType { SESSION, T3, APPID }

    private final AuthType authType;
    private final String username;      // T3/SESSION：u-xxx 去前缀后的用户名；APPID：appId
    private final String displayName;
    private final String tenantId;
    private final String org;
    private final Map<String, DataScope> permissions; // 权限码 -> 数据范围（APPID 时为空 = 无限制）
    private final String toolScope;     // T3 限定单工具
    private final String delegationChain; // T3 act 链 JSON（审计透传）
    private final String traceId;       // W3C traceparent 中的 trace-id

    public AuthContext(AuthType authType, String username, String displayName, String tenantId,
                       String org, Map<String, DataScope> permissions, String toolScope,
                       String delegationChain, String traceId) {
        this.authType = authType;
        this.username = username;
        this.displayName = displayName;
        this.tenantId = tenantId;
        this.org = org;
        this.permissions = permissions == null ? Collections.emptyMap() : permissions;
        this.toolScope = toolScope;
        this.delegationChain = delegationChain;
        this.traceId = traceId;
    }

    public boolean hasPermission(String code) {
        return permissions.containsKey(code);
    }

    public DataScope scopeOf(String code) {
        return permissions.get(code);
    }

    // ---------- ThreadLocal ----------
    private static final ThreadLocal<AuthContext> HOLDER = new ThreadLocal<>();

    public static void set(AuthContext ctx) {
        HOLDER.set(ctx);
    }

    public static AuthContext get() {
        return HOLDER.get();
    }

    public static void clear() {
        HOLDER.remove();
    }
}
