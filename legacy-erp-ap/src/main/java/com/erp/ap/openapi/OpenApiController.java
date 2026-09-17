package com.erp.ap.openapi;

import com.erp.ap.boapi.BoApiException;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Open API（appid 直连、租户级、无组织过滤）—— 历史事故口径的复现端点。
 *
 * ★ 这就是「页面 50 条 vs Open API 5000+ 条」事故的 Open API 侧：
 *   凭据映射租户，绕过用户数据权限；返回全租户发票且不做口径披露。
 *   （保留它是为了演示事故与 BO API 的对照，生产上此类端点应下线或收敛。）
 */
@RestController
@RequestMapping("/openapi")
@RequiredArgsConstructor
public class OpenApiController {

    private final EntityManager entityManager;
    private final JdbcTemplate jdbcTemplate;

    /** 事故端点：返回租户内全部发票（无组织过滤、无披露）。 */
    @GetMapping("/invoices")
    public Map<String, Object> invoices(@RequestParam(defaultValue = "10000") int limit) {
        var ctx = com.erp.ap.security.AuthContext.get();
        String tenantId = ctx.getTenantId();
        Number total = (Number) entityManager.createNativeQuery(
                        "SELECT count(*) FROM invoice WHERE tenant_id = ?")
                .setParameter(1, tenantId)
                .getSingleResult();
        List<Map<String, Object>> items = jdbcTemplate.queryForList(
                "SELECT invoice_no, org, amount_cny, tax_code, status, validation_status, period "
                        + "FROM invoice WHERE tenant_id = ? ORDER BY invoice_no LIMIT ?",
                tenantId, Math.min(limit, 20000));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", total.longValue());
        out.put("returned", items.size());
        out.put("items", items);
        return out;
    }

    /** bulk 种子管理端点（幂等：已有则跳过）。 */
    @PostMapping("/admin/bulk-seed")
    public Map<String, Object> bulkSeed(@RequestParam(defaultValue = "5000") int count) {
        int inserted = BulkSeeder.ensureBulk(jdbcTemplate, count);
        return Map.of("inserted", inserted, "target", count);
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("ok", true);
    }
}
