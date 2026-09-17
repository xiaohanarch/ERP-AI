package com.erp.ap.security;

import com.erp.ap.repo.ErpUserRepo;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.hibernate.Session;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 请求级认证/租户过滤器：
 *  1) 解析 traceparent -> MDC traceId（审计与错误信封透传）；
 *  2) 按路径族解析主体（会话 cookie / T3 令牌 / Open API 凭据）；
 *  3) 激活 Hibernate 租户过滤器（强制 WHERE tenant_id = ?）。
 */
@Component
@RequiredArgsConstructor
public class AuthFilter extends OncePerRequestFilter {

    private final TokenVerifier tokenVerifier;
    private final PermissionService permissionService;
    private final ErpUserRepo userRepo;
    private final jakarta.persistence.EntityManager entityManager;

    @Value("${erp.internal-secret}")
    private String internalSecret;

    /** 页面会话存储（演示用内存实现；重启失效可接受）。 */
    private static final Map<String, String> SESSIONS = new ConcurrentHashMap<>();

    public static void putSession(String sessionId, String username) {
        SESSIONS.put(sessionId, username);
    }

    public static String invalidateSession(String sessionId) {
        return SESSIONS.remove(sessionId);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String traceId = parseTraceId(request.getHeader("traceparent"));
        if (traceId == null) {
            traceId = UUID.randomUUID().toString().replace("-", "");
        }
        MDC.put("traceId", traceId);
        try {
            AuthContext ctx = resolve(request, response);
            if (ctx != null) {
                AuthContext.set(ctx);
                enableTenantFilter(ctx.getTenantId());
                chain.doFilter(request, response);
            }
        } finally {
            AuthContext.clear();
            MDC.remove("traceId");
        }
    }

    private AuthContext resolve(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String path = request.getRequestURI();

        // 无需认证：页面、登录、健康、元数据、内部端点（内部端点另行校验密钥）
        // /uiapi/auth/* 由控制器自行校验（verify=网关密钥；session-login=T1；logout=幂等）
        if (path.equals("/") || path.equals("/login") || path.equals("/error")
                || path.equals("/actuator/health") || path.startsWith("/metadata")
                || path.equals("/uiapi/auth/verify")
                || path.equals("/uiapi/auth/session-login")
                || path.equals("/uiapi/auth/logout")
                || path.startsWith("/internal/")) {
            if (path.startsWith("/internal/")) {
                String secret = request.getHeader("X-Internal-Secret");
                if (secret == null || !MessageDigest.isEqual(
                        secret.getBytes(StandardCharsets.UTF_8), internalSecret.getBytes(StandardCharsets.UTF_8))) {
                    response.sendError(401, "internal secret required");
                    return null;
                }
            }
            return new AuthContext(AuthContext.AuthType.SESSION, null, null, null, null,
                    Map.of(), null, null, MDC.get("traceId"));
        }

        // Open API：appid 直连（租户级 -> 事故口径）
        if (path.startsWith("/openapi/")) {
            return resolveAppId(request, response);
        }

        // BO API / MCP：仅接受网关铸造的 T3
        if (path.startsWith("/boapi/") || path.startsWith("/mcp")) {
            return resolveT3(request, response);
        }

        // UI API：会话 cookie 或（会话建立用的）T1
        if (path.startsWith("/uiapi/") || path.startsWith("/ui/")) {
            return resolveSessionOrT1(request, response);
        }

        return new AuthContext(AuthContext.AuthType.SESSION, null, null, null, null,
                Map.of(), null, null, MDC.get("traceId"));
    }

    private AuthContext resolveT3(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String token = bearer(request);
        if (token == null) {
            response.sendError(401, "Bearer T3 required");
            return null;
        }
        TokenVerifier.VerifiedToken vt;
        try {
            vt = tokenVerifier.verify(token);
        } catch (JwtException e) {
            response.sendError(401, "invalid token: " + e.getMessage());
            return null;
        }
        if (!tokenVerifier.isT3(vt.azp())) {
            response.sendError(401, "BO API only accepts gateway-minted T3 (azp=erp-ai-action)");
            return null;
        }
        String username = stripUserPrefix(vt.subject());
        var perms = permissionService.loadPermissions(username, vt.tenantId());
        var user = permissionService.loadUser(username);
        return new AuthContext(AuthContext.AuthType.T3, username, user.getDisplayName(),
                vt.tenantId(), user.getOrg(), perms,
                vt.scope() == null || vt.scope().isEmpty() ? null : vt.scope().get(0),
                vt.actChainJson(), MDC.get("traceId"));
    }

    private AuthContext resolveSessionOrT1(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String sessionCookie = cookie(request, "ERP_SESSION");
        if (sessionCookie != null && SESSIONS.containsKey(sessionCookie)) {
            String username = SESSIONS.get(sessionCookie);
            var user = userRepo.findByUsername(username).orElse(null);
            if (user == null) {
                response.sendError(401, "session user missing");
                return null;
            }
            var perms = permissionService.loadPermissions(username, null);
            return new AuthContext(AuthContext.AuthType.SESSION, username, user.getDisplayName(),
                    user.getTenantId(), user.getOrg(), perms, null, null, MDC.get("traceId"));
        }
        // 会话建立：携带网关 T1（azp=surface-*）
        String token = bearer(request);
        if (token != null) {
            try {
                var vt = tokenVerifier.verify(token);
                if (tokenVerifier.isSurfaceToken(vt.azp())) {
                    String username = stripUserPrefix(vt.subject());
                    var user = userRepo.findByUsername(username).orElse(null);
                    if (user != null && user.getTenantId().equals(vt.tenantId())) {
                        var perms = permissionService.loadPermissions(username, null);
                        return new AuthContext(AuthContext.AuthType.SESSION, username, user.getDisplayName(),
                                user.getTenantId(), user.getOrg(), perms, null, null, MDC.get("traceId"));
                    }
                }
            } catch (JwtException ignored) {
                // fallthrough
            }
        }
        response.sendError(401, "ERP session required");
        return null;
    }

    private AuthContext resolveAppId(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String appId = headerOrParam(request, "X-App-Id", "appId");
        String appSecret = headerOrParam(request, "X-App-Secret", "appSecret");
        if (appId == null || appSecret == null) {
            response.sendError(401, "appId/appSecret required");
            return null;
        }
        var hash = sha256(appSecret);
        var rows = entityManager.createNativeQuery(
                        "SELECT tenant_id, all_orgs FROM openapi_credential WHERE app_id = ? AND secret_hash = ?")
                .setParameter(1, appId)
                .setParameter(2, hash)
                .getResultList();
        if (rows.isEmpty()) {
            response.sendError(401, "invalid appId/appSecret");
            return null;
        }
        Object[] row = (Object[]) rows.get(0);
        return new AuthContext(AuthContext.AuthType.APPID, appId, appId, (String) row[0], null,
                Map.of(), null, null, MDC.get("traceId"));
    }

    private void enableTenantFilter(String tenantId) {
        if (tenantId != null) {
            Session session = entityManager.unwrap(Session.class);
            session.enableFilter("tenant").setParameter("tid", tenantId);
        }
    }

    // ---------- 工具方法 ----------
    public static String stripUserPrefix(String sub) {
        return sub != null && sub.startsWith("u-") ? sub.substring(2) : sub;
    }

    private static String bearer(HttpServletRequest request) {
        String h = request.getHeader("Authorization");
        return h != null && h.startsWith("Bearer ") ? h.substring(7) : null;
    }

    private static String cookie(HttpServletRequest request, String name) {
        if (request.getCookies() == null) {
            return null;
        }
        for (var c : request.getCookies()) {
            if (name.equals(c.getName())) {
                return c.getValue();
            }
        }
        return null;
    }

    private static String headerOrParam(HttpServletRequest request, String header, String param) {
        String h = request.getHeader(header);
        return h != null ? h : request.getParameter(param);
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String parseTraceId(String traceparent) {
        if (traceparent == null || traceparent.length() < 55 || traceparent.length() > 200) {
            return null;
        }
        String[] parts = traceparent.split("-");
        if (parts.length >= 2 && parts[0].length() == 2) {
            return parts[1];
        }
        return null;
    }
}
