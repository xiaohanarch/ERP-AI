package com.erp.ap.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * 事件 outbox：ap.invoice.blocked 等（事件契约在 Phase 2 初冻结）。
 * 幂等发布（event_key 唯一），hub 通过 /internal/events 拉取并确认。
 */
@Service
@RequiredArgsConstructor
public class OutboxService {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public void publishInvoiceBlocked(com.erp.ap.domain.Invoice invoice, List<Map<String, Object>> findings) {
        try {
            Map<String, Object> payload = new java.util.LinkedHashMap<>();
            payload.put("eventType", "ap.invoice.blocked");
            payload.put("tenantId", invoice.getTenantId());
            payload.put("invoiceNo", invoice.getInvoiceNo());
            payload.put("org", invoice.getOrg());
            payload.put("amountCny", invoice.getAmountCny());
            payload.put("supplierId", invoice.getSupplierId());
            payload.put("findings", findings);
            payload.put("ruleSetVersion", com.erp.ap.rules.RuleEngine.RULESET_VERSION);
            payload.put("occurredAt", java.time.OffsetDateTime.now().toString());
            String payloadJson = objectMapper.writeValueAsString(payload);
            String eventKey = "ap.invoice.blocked:" + invoice.getInvoiceNo();
            jdbcTemplate.update(
                    "INSERT INTO outbox_event (event_key, event_type, payload_json) VALUES (?, ?, ?) ON CONFLICT (event_key) DO NOTHING",
                    eventKey, "ap.invoice.blocked", payloadJson);
        } catch (Exception e) {
            // 事件发布失败不阻断校验主流程（演示口径）
            throw new IllegalStateException("outbox publish failed", e);
        }
    }

    public List<Map<String, Object>> pollUnconsumed(int limit) {
        return jdbcTemplate.queryForList(
                "SELECT id, event_key, event_type, payload_json, created_at FROM outbox_event WHERE consumed = false ORDER BY id LIMIT ?",
                limit);
    }

    public void ack(List<Long> ids) {
        for (Long id : ids) {
            jdbcTemplate.update("UPDATE outbox_event SET consumed = true WHERE id = ?", id);
        }
    }

    /**
     * 事件重投（消息平台标配能力：订阅方调试/补投场景）。
     * 以原事件载荷为基础注入 redelivered 标记，新 event_key 落 outbox ——
     * 走与首发完全相同的消费链路（hub 拉取 -> 平台内 Agent + 租户消息分发）。
     */
    public Map<String, Object> republish(String eventKey) {
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT id, event_key, event_type, payload_json FROM outbox_event WHERE event_key = ?", eventKey);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("event not found: " + eventKey);
        }
        Map<String, Object> origin = rows.get(0);
        try {
            com.fasterxml.jackson.databind.JsonNode node = objectMapper.readTree((String) origin.get("payload_json"));
            if (node.isObject()) {
                ((com.fasterxml.jackson.databind.node.ObjectNode) node).put("redelivered", true);
            }
            String newKey = eventKey + ":re-" + java.util.UUID.randomUUID().toString().substring(0, 8);
            jdbcTemplate.update(
                    "INSERT INTO outbox_event (event_key, event_type, payload_json) VALUES (?, ?, ?)",
                    newKey, origin.get("event_type"), objectMapper.writeValueAsString(node));
            return Map.of("eventKey", newKey, "eventType", origin.get("event_type"), "redelivered", true);
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("republish failed", e);
        }
    }
}
