package com.erp.ap.uiapi;

import com.erp.ap.service.InvoiceQueryService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 页面数据 API（会话 + 三维数据权限 -> 「页面 50 条」口径）。 */
@RestController
@RequestMapping("/uiapi")
@RequiredArgsConstructor
public class UiInvoiceController {

    private final InvoiceQueryService invoiceQueryService;

    @GetMapping("/me")
    public Map<String, Object> me() {
        var ctx = com.erp.ap.security.AuthContext.get();
        return Map.of(
                "username", ctx.getUsername() == null ? "" : ctx.getUsername(),
                "displayName", ctx.getDisplayName() == null ? "" : ctx.getDisplayName(),
                "tenantId", ctx.getTenantId() == null ? "" : ctx.getTenantId(),
                "org", ctx.getOrg() == null ? "" : ctx.getOrg(),
                "permissions", ctx.getPermissions().keySet().stream().sorted().toList());
    }

    @GetMapping("/invoices")
    public Map<String, Object> invoices() {
        return invoiceQueryService.uiList();
    }
}
