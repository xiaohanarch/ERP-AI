package com.erp.ap.boapi;

import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.Map;

/** 统一错误信封：error{code, category, message, field, retryable, retry_after_seconds, remediation, trace_id} */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BoApiException.class)
    public ResponseEntity<Map<String, Object>> handle(BoApiException e) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", e.getCode());
        error.put("category", e.getCategory());
        error.put("message", e.getMessage());
        error.put("field", null);
        error.put("retryable", e.isRetryable());
        error.put("retry_after_seconds", e.getRetryAfterSeconds());
        error.put("remediation", e.getRemediation());
        error.put("trace_id", MDC.get("traceId"));
        return ResponseEntity.status(httpStatusOf(e.getCategory())).body(Map.of("error", error));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleGeneric(Exception e) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", "AP.INTERNAL_ERROR");
        error.put("category", "retryable_failure");
        error.put("message", "服务内部错误（演示环境，详情见服务日志）");
        error.put("field", null);
        error.put("retryable", true);
        error.put("retry_after_seconds", 5);
        error.put("remediation", null);
        error.put("trace_id", MDC.get("traceId"));
        return ResponseEntity.status(500).body(Map.of("error", error));
    }

    private HttpStatus httpStatusOf(String category) {
        return switch (category) {
            case "not_found" -> HttpStatus.NOT_FOUND;
            case "state_conflict" -> HttpStatus.CONFLICT;
            case "permission_denied", "gateway_policy" -> HttpStatus.FORBIDDEN;
            case "validation_error" -> HttpStatus.BAD_REQUEST;
            default -> HttpStatus.SERVICE_UNAVAILABLE;
        };
    }
}
