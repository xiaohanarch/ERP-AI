package com.erp.ap.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 网关签发令牌校验（HS256，共享密钥）。
 * T1（azp=surface-*）用于页面会话建立；T3（azp=erp-ai-action）用于 BO API/MCP。
 */
@Component
public class TokenVerifier {

    private final SecretKey key;

    public TokenVerifier(@Value("${erp.jwt-secret}") String secret) {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    public record VerifiedToken(String subject, String tenantId, String azp, List<String> scope, String actChainJson) {}

    /**
     * 校验并解析令牌；失败抛 JwtException。
     */
    public VerifiedToken verify(String token) {
        Claims claims = Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
        String sub = claims.getSubject();
        String tid = claims.get("tid", String.class);
        String azp = claims.get("azp", String.class);
        Object rawScope = claims.get("scope");
        List<String> scope = rawScope instanceof List<?> list
                ? list.stream().map(String::valueOf).toList()
                : List.of();
        Object act = claims.get("act");
        String actJson = null;
        if (act != null) {
            try {
                actJson = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(act);
            } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
                actJson = String.valueOf(act);
            }
        }
        return new VerifiedToken(sub, tid, azp, scope, actJson);
    }

    public boolean isT3(String azp) {
        return "erp-ai-action".equals(azp);
    }

    public boolean isSurfaceToken(String azp) {
        return azp != null && (azp.equals("surface-erp-page") || azp.equals("workbuddy"));
    }

    public static JwtException invalid(String reason) {
        return new JwtException(reason);
    }
}
