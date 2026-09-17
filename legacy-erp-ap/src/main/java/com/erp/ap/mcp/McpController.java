package com.erp.ap.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * MCP Streamable HTTP 端点（JSON-RPC 2.0）。
 * 支持：initialize / notifications/initialized / tools/list / tools/call。
 * 认证：Bearer T3（azp=erp-ai-action，scope=单工具）—— 由 AuthFilter 强制。
 * 审批透传：X-BO-Approver / X-BO-Approval-Ref（网关 OT 验证后附加）。
 */
@RestController
@RequestMapping("/mcp")
@RequiredArgsConstructor
public class McpController {

    private final McpToolManifest manifest;
    private final McpDispatcher dispatcher;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> handle(@RequestBody String body,
                                         @RequestHeader(value = "X-BO-Approver", required = false) String approver,
                                         @RequestHeader(value = "X-BO-Approval-Ref", required = false) String approvalRef) {
        JsonNode req;
        try {
            req = objectMapper.readTree(body);
        } catch (Exception e) {
            return jsonRpcError(null, -32700, "Parse error");
        }
        JsonNode idNode = req.get("id");
        String method = req.path("method").asText("");
        boolean isNotification = idNode == null || idNode.isNull();

        // 通知：无 id，按协议返回 202 空体
        if (isNotification) {
            return ResponseEntity.accepted().build();
        }

        return switch (method) {
            case "initialize" -> initialize(idNode);
            case "tools/list" -> toolsList(idNode);
            case "tools/call" -> toolsCall(req, idNode, approver, approvalRef);
            default -> jsonRpcError(idNode, -32601, "Method not found: " + method);
        };
    }

    private ResponseEntity<String> initialize(JsonNode idNode) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("protocolVersion", "2024-11-05");
        result.put("capabilities", Map.of("tools", Map.of("listChanged", false)));
        result.put("serverInfo", Map.of(
                "name", "erp-ap-mcp",
                "version", "1.0.0",
                "appid", "erp-ap",
                "specVersion", manifest.specVersion()));
        return jsonRpcResult(idNode, result);
    }

    private ResponseEntity<String> toolsList(JsonNode idNode) {
        return jsonRpcResult(idNode, Map.of("tools", manifest.toMcpTools()));
    }

    @SuppressWarnings("unchecked")
    private ResponseEntity<String> toolsCall(JsonNode req, JsonNode idNode, String approver, String approvalRef) {
        String name = req.path("params").path("name").asText();
        Map<String, Object> arguments = new LinkedHashMap<>();
        JsonNode argsNode = req.path("params").path("arguments");
        if (argsNode.isObject()) {
            arguments = objectMapper.convertValue(argsNode, Map.class);
        }
        McpDispatcher.ToolCallResult r = dispatcher.call(name, arguments, approver, approvalRef);

        Map<String, Object> content = new LinkedHashMap<>();
        content.put("type", "text");
        content.put("text", r.textJson());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("content", java.util.List.of(content));
        if (r.isError()) {
            result.put("isError", true);
        }
        return jsonRpcResult(idNode, result);
    }

    // ---------- JSON-RPC 信封 ----------

    private ResponseEntity<String> jsonRpcResult(JsonNode idNode, Object result) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.set("jsonrpc", objectMapper.valueToTree("2.0"));
        envelope.set("id", idNode == null ? objectMapper.nullNode() : idNode);
        envelope.set("result", objectMapper.valueToTree(result));
        return ResponseEntity.ok(envelope.toString());
    }

    private ResponseEntity<String> jsonRpcError(JsonNode idNode, int code, String message) {
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.set("jsonrpc", objectMapper.valueToTree("2.0"));
        envelope.set("id", idNode == null ? objectMapper.nullNode() : idNode);
        ObjectNode error = envelope.putObject("error");
        error.put("code", code);
        error.put("message", message);
        return ResponseEntity.status(code == -32700 ? HttpStatus.BAD_REQUEST : HttpStatus.OK).body(envelope.toString());
    }
}
