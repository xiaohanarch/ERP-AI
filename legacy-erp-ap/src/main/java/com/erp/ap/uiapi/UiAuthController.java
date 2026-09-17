package com.erp.ap.uiapi;

import com.erp.ap.security.AuthFilter;
import com.erp.ap.security.TokenVerifier;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;

/**
 * 页面会话与凭据校验。
 *  - POST /uiapi/auth/verify      ：网关 SSO 登录时校验用户名口令（X-Internal-Secret 保护）
 *  - POST /uiapi/auth/session-login：携带网关 T1 建立页面会话（ERP_SESSION cookie）
 *  - POST /uiapi/auth/logout      ：退出
 */
@RestController
@RequestMapping("/uiapi/auth")
@RequiredArgsConstructor
public class UiAuthController {

    private final com.erp.ap.repo.ErpUserRepo userRepo;
    private final TokenVerifier tokenVerifier;

    @Value("${erp.internal-secret}")
    private String internalSecret;

    /** 网关调用：校验用户名口令（不入会话）。 */
    @PostMapping("/verify")
    public ResponseEntity<Map<String, Object>> verify(@RequestHeader(value = "X-Internal-Secret", required = false) String secret,
                                                      @RequestBody Map<String, String> body) {
        if (secret == null || !MessageDigest.isEqual(
                secret.getBytes(StandardCharsets.UTF_8), internalSecret.getBytes(StandardCharsets.UTF_8))) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false, "message", "internal secret required"));
        }
        String username = body.getOrDefault("username", "");
        String password = body.getOrDefault("password", "");
        var user = userRepo.findByUsername(username).orElse(null);
        if (user == null || !user.getPasswordHash().equalsIgnoreCase(sha256(password))) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false, "message", "用户名或口令错误"));
        }
        return ResponseEntity.ok(Map.of(
                "ok", true,
                "sub", "u-" + username,
                "username", username,
                "displayName", user.getDisplayName(),
                "tenantId", user.getTenantId(),
                "org", user.getOrg(),
                "title", user.getTitle() == null ? "" : user.getTitle()));
    }

    /** 携带网关 T1（azp=surface-erp-page）建立页面会话。 */
    @PostMapping("/session-login")
    public ResponseEntity<Map<String, Object>> sessionLogin(@RequestBody Map<String, String> body,
                                                            HttpServletResponse response) {
        String token = body.get("token");
        if (token == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false, "message", "token required"));
        }
        try {
            var vt = tokenVerifier.verify(token);
            if (!tokenVerifier.isSurfaceToken(vt.azp())) {
                return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false, "message", "非 surface 令牌"));
            }
            String username = AuthFilter.stripUserPrefix(vt.subject());
            var user = userRepo.findByUsername(username).orElse(null);
            if (user == null || !user.getTenantId().equals(vt.tenantId())) {
                return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false, "message", "用户不存在或租户不符"));
            }
            String sessionId = UUID.randomUUID().toString();
            AuthFilter.putSession(sessionId, username);
            Cookie cookie = new Cookie("ERP_SESSION", sessionId);
            cookie.setPath("/");
            cookie.setHttpOnly(true);
            response.addCookie(cookie);
            return ResponseEntity.ok(Map.of("ok", true, "displayName", user.getDisplayName(), "tenantId", user.getTenantId()));
        } catch (JwtException e) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("ok", false, "message", "令牌无效"));
        }
    }

    @PostMapping("/logout")
    public Map<String, Object> logout(@CookieValue(value = "ERP_SESSION", required = false) String sessionId,
                                      HttpServletResponse response) {
        if (sessionId != null) {
            AuthFilter.invalidateSession(sessionId);
        }
        Cookie cookie = new Cookie("ERP_SESSION", "");
        cookie.setPath("/");
        cookie.setMaxAge(0);
        response.addCookie(cookie);
        return Map.of("ok", true);
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
