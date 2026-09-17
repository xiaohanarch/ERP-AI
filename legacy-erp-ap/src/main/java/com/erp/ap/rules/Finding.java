package com.erp.ap.rules;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/** 单条规则命中结果。 */
public record Finding(
        String ruleId,
        RuleGroup ruleGroup,
        Severity severity,
        String message,
        String subject,
        Map<String, BigDecimal> amounts,
        String remediationAction,
        List<String> remediationRelatedOperations) {

    public Map<String, Object> toMap() {
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("ruleId", ruleId);
        m.put("ruleGroup", ruleGroup.name());
        m.put("severity", severity.name());
        m.put("message", message);
        m.put("subject", subject);
        m.put("amounts", amounts);
        if (remediationAction != null) {
            m.put("remediation", Map.of(
                    "action", remediationAction,
                    "relatedOperations", remediationRelatedOperations == null ? List.of() : remediationRelatedOperations));
        }
        return m;
    }
}
