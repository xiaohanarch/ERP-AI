package com.erp.ap;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.web.client.RestTemplate;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * ★ 权限平价测试（Phase 0 验收项）：
 *   1) 页面（会话）口径 = 50 条；
 *   2) BO API（张三 T3）阻断筛查与页面同数据权限口径（集合一致）；
 *   3) Open API（appid 直连、租户级）= 5000+ 条（事故复现）。
 *
 * 运行方式（需 compose 起 postgres 后，容器内执行）：
 *   mvn test -Dtest=PermissionParityTest -Dspring.datasource.url=$PARITY_DB_URL ...
 * 环境变量 PARITY_DB_URL 存在时启用。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("parity")
@EnabledIfEnvironmentVariable(named = "PARITY_DB_URL", matches = ".+")
class PermissionParityTest {

    @LocalServerPort
    int port;

    @Value("${erp.jwt-secret}")
    String jwtSecret;

    private final RestTemplate rest = new RestTemplate();
    private static final String GW_ISSUER = "erp-ai-action";

    private String mintT3(String sub, String tid, String tool) {
        return Jwts.builder()
                .issuer(GW_ISSUER)
                .subject(sub)
                .claim("tid", tid)
                .claim("azp", "erp-ai-action")
                .claim("scope", List.of(tool))
                .claim("act", Map.of("sub", "agent:ap-copilot", "act", Map.of("sub", "erp-ai-hub")))
                .issuedAt(Date.from(Instant.now()))
                .expiration(Date.from(Instant.now().plusSeconds(60)))
                .signWith(Keys.hmacShaKeyFor(jwtSecret.getBytes(StandardCharsets.UTF_8)))
                .compact();
    }

    @Test
    @SuppressWarnings("unchecked")
    void uiAndBoApiShareSameScopeWhileOpenApiLeaks() {
        // ---- 1) 页面口径：张三 ORG-EAST-PROC = 50 条 ----
        //（会话路径依赖 cookie，此处以 T1 语义等价验证：直接用带会话头的调用不便，
        //  平价断言核心在 BO 与 Open 的对照，页面 50 条由 scripts/demo/scene_1 断言。）

        // ---- 2) BO API：张三 T3 阻断筛查（应只见本组织，且数量 <= 50） ----
        HttpHeaders boHeaders = new HttpHeaders();
        boHeaders.setBearerAuth(mintT3("u-zhangsan", "T-EAST", "ap.invoice.listBlocked"));
        ResponseEntity<Map> boResp = rest.exchange(
                "http://localhost:" + port + "/boapi/invoices/blocked?pageSize=100",
                HttpMethod.GET, new HttpEntity<>(boHeaders), Map.class);
        assertEquals(200, boResp.getStatusCode().value());
        Map<String, Object> boBody = boResp.getBody();
        List<Map<String, Object>> boItems = (List<Map<String, Object>>) boBody.get("items");
        long boTotal = ((Number) ((Map<String, Object>) boBody.get("pageInfo")).get("total")).longValue();
        assertTrue(boTotal <= 50, "张三 BO 口径应 <= 页面 50 条，实际 " + boTotal);
        assertTrue(boTotal >= 8, "张三 BO 口径应含多条阻断发票，实际 " + boTotal);
        for (Map<String, Object> item : boItems) {
            assertEquals("ORG-EAST-PROC", item.get("org"), "BO 口径不得越出数据权限组织");
        }
        // 披露字段（E-2）
        Map<String, Object> filtered = (Map<String, Object>) boBody.get("filteredByDimension");
        List<String> dims = (List<String>) filtered.get("dimensions");
        assertTrue(dims.contains("org"), "filteredByDimension 必须披露 org 维度");

        // ---- 3) Open API：租户级 = 5000+ 条（事故复现） ----
        HttpHeaders openHeaders = new HttpHeaders();
        openHeaders.set("X-App-Id", "open-erp-east");
        openHeaders.set("X-App-Secret", "open-east-secret");
        ResponseEntity<Map> openResp = rest.exchange(
                "http://localhost:" + port + "/openapi/invoices",
                HttpMethod.GET, new HttpEntity<>(openHeaders), Map.class);
        assertEquals(200, openResp.getStatusCode().value());
        long openTotal = ((Number) openResp.getBody().get("total")).longValue();
        assertTrue(openTotal >= 5050, "Open API 事故口径应 >= 5050（bulk 5000 + 特殊 50+），实际 " + openTotal);

        // ---- 4) 跨租户负向：张三查 T-UNI 发票 -> NOT_FOUND ----
        HttpHeaders notFoundHeaders = new HttpHeaders();
        notFoundHeaders.setBearerAuth(mintT3("u-zhangsan", "T-EAST", "ap.invoice.checkValidation"));
        ResponseEntity<Map> nfResp = rest.exchange(
                "http://localhost:" + port + "/boapi/invoices/INV-B-001/check-validation",
                HttpMethod.GET, new HttpEntity<>(notFoundHeaders), Map.class);
        assertEquals(404, nfResp.getStatusCode().value());
        Map<String, Object> err = (Map<String, Object>) nfResp.getBody().get("error");
        assertEquals("AP.INVOICE_NOT_FOUND", err.get("code"));
    }
}
