package com.erp.ap.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MCP 工具清单加载器：bo-tools-manifest.json 由构建期从 boapi-spec/bo-ap.yaml
 * 生成（scripts/gen_manifest.py）—— 规格即工具，Java 侧不手写工具定义。
 */
@Component
public class McpToolManifest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private List<ToolDef> tools = new ArrayList<>();
    private String specVersion;
    private String rulesetVersion;

    public record ToolDef(String name, String summary, String description, String kind, boolean irreversible,
                          String sodGroup, List<String> permissions, List<String> errorCodes,
                          Map<String, Object> inputSchema, Map<String, Map<String, String>> binding) {}

    @PostConstruct
    void load() {
        try {
            JsonNode root = objectMapper.readTree(new ClassPathResource("bo-tools-manifest.json").getInputStream());
            specVersion = root.path("spec_version").asText();
            rulesetVersion = root.path("ruleset_version").asText();
            List<ToolDef> loaded = new ArrayList<>();
            for (JsonNode t : root.path("tools")) {
                Map<String, Object> schema = objectMapper.convertValue(t.path("input_schema"), Map.class);
                Map<String, Map<String, String>> binding = new LinkedHashMap<>();
                t.path("binding").fields().forEachRemaining(e ->
                        binding.put(e.getKey(), objectMapper.convertValue(e.getValue(), Map.class)));
                List<String> permissions = new ArrayList<>();
                t.path("permissions").forEach(n -> permissions.add(n.asText()));
                List<String> errorCodes = new ArrayList<>();
                t.path("error_codes").forEach(n -> errorCodes.add(n.asText()));
                loaded.add(new ToolDef(
                        t.path("name").asText(),
                        t.path("summary").asText(),
                        t.path("description").asText(),
                        t.path("kind").asText(),
                        t.path("irreversible").asBoolean(false),
                        t.path("sod_group").isTextual() ? t.path("sod_group").asText() : null,
                        permissions, errorCodes, schema, binding));
            }
            this.tools = List.copyOf(loaded);
        } catch (Exception e) {
            throw new IllegalStateException("bo-tools-manifest.json 加载失败", e);
        }
    }

    public List<ToolDef> tools() {
        return tools;
    }

    public ToolDef find(String name) {
        return tools.stream().filter(t -> t.name().equals(name)).findFirst().orElse(null);
    }

    public String specVersion() {
        return specVersion;
    }

    public String rulesetVersion() {
        return rulesetVersion;
    }

    /** MCP tools/list 响应体。 */
    public List<Map<String, Object>> toMcpTools() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ToolDef t : tools) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", t.name());
            m.put("description", t.summary() + "\n\n" + t.description()
                    + (t.irreversible() ? "\n\n[不可逆写操作：网关强制审批]" : ""));
            m.put("inputSchema", t.inputSchema());
            out.add(m);
        }
        return out;
    }
}
