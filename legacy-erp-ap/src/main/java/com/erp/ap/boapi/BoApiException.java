package com.erp.ap.boapi;

import lombok.Getter;

import java.util.Map;

/**
 * 统一业务异常（六类 category），由 GlobalExceptionHandler 转为错误信封。
 * category -> HTTP 映射：not_found=404, state_conflict=409, permission_denied=403,
 *                        retryable_failure=503, gateway_policy=403, validation_error=400
 */
@Getter
public class BoApiException extends RuntimeException {

    private final String code;
    private final String category;
    private final boolean retryable;
    private final Integer retryAfterSeconds;
    private final Map<String, Object> remediation;

    public BoApiException(String code, String category, String message, boolean retryable,
                           Integer retryAfterSeconds, Map<String, Object> remediation) {
        super(message);
        this.code = code;
        this.category = category;
        this.retryable = retryable;
        this.retryAfterSeconds = retryAfterSeconds;
        this.remediation = remediation;
    }

    public static BoApiException notFound(String code, String message) {
        return new BoApiException(code, "not_found", message, false, null, null);
    }

    public static BoApiException stateConflict(String code, String message) {
        return new BoApiException(code, "state_conflict", message, false, null, null);
    }

    public static BoApiException permissionDenied(String code, String message) {
        return new BoApiException(code, "permission_denied", message, false, null, null);
    }

    public static BoApiException retryable(String code, String message, int retryAfterSeconds) {
        return new BoApiException(code, "retryable_failure", message, true, retryAfterSeconds, null);
    }

    public static BoApiException validation(String code, String message) {
        return new BoApiException(code, "validation_error", message, false, null, null);
    }
}
