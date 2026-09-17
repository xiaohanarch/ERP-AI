package com.erp.ap.mcp;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.service.BoToolExecutor;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * MCP 工具分发器：manifest 定义工具，本分发器统一路由到 BoToolExecutor。
 * （对 Spring AI MCP 版本演进的缓解：manifest + 通用分发器单模块。）
 */
@Component
@RequiredArgsConstructor
public class McpDispatcher {

    private final McpToolManifest manifest;
    private final BoToolExecutor executor;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public record ToolCallResult(boolean isError, String textJson) {}

    public ToolCallResult call(String toolName, Map<String, Object> arguments,
                               String approver, String approvalRef) {
        McpToolManifest.ToolDef tool = manifest.find(toolName);
        if (tool == null) {
            return new ToolCallResult(true, errorEnvelope("AP.VALIDATION_ERROR", "validation_error",
                    "未知工具：" + toolName, false));
        }
        // T3 scope 必须精确覆盖被调工具（单工具短时令牌）
        var ctx = com.erp.ap.security.AuthContext.get();
        if (ctx.getToolScope() != null && !toolName.equals(ctx.getToolScope())) {
            return new ToolCallResult(true, errorEnvelope("AP.PERMISSION_DENIED", "permission_denied",
                    "T3 scope 不包含工具 " + toolName, false));
        }
        // 必填参数校验（manifest inputSchema.required）
        Object requiredNode = tool.inputSchema().getOrDefault("required", java.util.List.of());
        if (requiredNode instanceof Iterable<?> requiredList) {
            for (Object req : requiredList) {
                if (arguments == null || arguments.get(String.valueOf(req)) == null) {
                    return new ToolCallResult(true, errorEnvelope("AP.VALIDATION_ERROR", "validation_error",
                            "缺少必填参数：" + req, false));
                }
            }
        }
        Map<String, Object> args = arguments == null ? new HashMap<>() : new HashMap<>(arguments);
        try {
            Map<String, Object> result = executor.execute(toolName, args, approver, approvalRef);
            // 元信息回填（MCP 侧可见的操作性质与版本）
            result.put("_meta", Map.of(
                    "tool", toolName,
                    "kind", tool.kind(),
                    "irreversible", tool.irreversible(),
                    "specVersion", manifest.specVersion(),
                    "ruleSetVersion", manifest.rulesetVersion()));
            return new ToolCallResult(false, objectMapper.writeValueAsString(result));
        } catch (BoApiException e) {
            return new ToolCallResult(true, errorEnvelope(e.getCode(), e.getCategory(), e.getMessage(), e.isRetryable()));
        } catch (Exception e) {
            return new ToolCallResult(true, errorEnvelope("AP.INTERNAL_ERROR", "retryable_failure",
                    "工具执行异常（演示环境，详见服务日志）", true));
        }
    }

    private String errorEnvelope(String code, String category, String message, boolean retryable) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", code);
        error.put("category", category);
        error.put("message", message);
        error.put("retryable", retryable);
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("error", error);
        try {
            return objectMapper.writeValueAsString(envelope);
        } catch (Exception e) {
            return "{\"error\":{\"code\":\"AP.INTERNAL_ERROR\"}}";
        }
    }
}
