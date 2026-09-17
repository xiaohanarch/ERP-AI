package com.erp.ap.rules;

import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 规则引擎：按（请求的规则组 ∩ 权限允许的规则组）执行，并输出被跳过的组。
 *
 * ★ 存量行为基线：权限不足时「静默跳过」规则组；BO API 适配层必须把跳过
 *   补齐为 completeness 披露 —— 这是「适配层一半工作量在 completeness」的演示点。
 */
@Component
public class RuleEngine {

    /** 组 -> 所需权限码（与 bo-ap.yaml x-bo-permissions.rule_group_permissions 同源）。 */
    public static final Map<RuleGroup, List<String>> GROUP_PERMISSIONS = Map.of(
            RuleGroup.MATCH, List.of("ap.invoice.read", "ap.po.read", "ap.gr.read"),
            RuleGroup.TAX, List.of("ap.taxcode.read"),
            RuleGroup.BUDGET, List.of("ap.budget.read"),
            RuleGroup.VENDOR, List.of("ap.vendor.read"));

    public static final String RULESET_VERSION = "AP-RS-1.2.0";

    private final List<Rule> rules;

    public RuleEngine(List<Rule> rules) {
        this.rules = List.copyOf(rules);
    }

    public record Evaluation(List<Map<String, Object>> findings, List<String> skippedGroups) {}

    /**
     * @param requestedGroups 请求的组（空 = 全部）
     * @param permissionSatisfied 权限判定回调（组级）
     */
    public Evaluation evaluate(Invoice invoice, List<InvoiceLine> lines, Rule.RuleContext ctx,
                               List<RuleGroup> requestedGroups, java.util.function.Predicate<RuleGroup> permissionSatisfied) {
        Set<RuleGroup> requested = requestedGroups == null || requestedGroups.isEmpty()
                ? Set.of(RuleGroup.values())
                : Set.copyOf(requestedGroups);

        List<Map<String, Object>> findings = new ArrayList<>();
        List<String> skipped = new ArrayList<>();
        for (RuleGroup group : List.of(RuleGroup.MATCH, RuleGroup.TAX, RuleGroup.BUDGET, RuleGroup.VENDOR)) {
            if (!requested.contains(group)) {
                continue;
            }
            if (!permissionSatisfied.test(group)) {
                skipped.add(group.name());
                continue;
            }
            for (Rule rule : rules) {
                if (rule.group() == group) {
                    rule.evaluate(invoice, lines, ctx).forEach(f -> findings.add(f.toMap()));
                }
            }
        }
        return new Evaluation(findings, skipped);
    }

    /** 从 findings 推导整体结果：任一 BLOCK -> BLOCKED；否则任一 WARN -> WARNED；否则 PASSED。 */
    public static String overallResultOf(List<Map<String, Object>> findings) {
        boolean warn = false;
        for (Map<String, Object> f : findings) {
            if ("BLOCK".equals(f.get("severity"))) {
                return "BLOCKED";
            }
            if ("WARN".equals(f.get("severity"))) {
                warn = true;
            }
        }
        return warn ? "WARNED" : "PASSED";
    }

    public List<Map<String, Object>> ruleCatalog() {
        List<Map<String, Object>> catalog = new ArrayList<>();
        for (Rule rule : rules) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("ruleId", rule.ruleId());
            m.put("ruleGroup", rule.group().name());
            m.put("severity", rule.severity().name());
            catalog.add(m);
        }
        return catalog;
    }
}
