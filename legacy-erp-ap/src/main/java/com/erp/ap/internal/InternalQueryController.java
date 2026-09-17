package com.erp.ap.internal;

import com.erp.ap.domain.ErpUser;
import com.erp.ap.security.PermissionService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 内部查询端点（网关消费；X-Internal-Secret 校验见 AuthFilter）。
 *  - GET /internal/permissions?username= ：权限码清单（网关审批决定时校验 ap.approval.decide）。
 */
@RestController
@RequestMapping("/internal")
@RequiredArgsConstructor
public class InternalQueryController {

    private final PermissionService permissionService;

    @GetMapping("/permissions")
    public ResponseEntity<Map<String, Object>> permissions(@RequestParam String username) {
        ErpUser user;
        try {
            user = permissionService.loadUser(username);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Map.of("ok", false, "message", "用户不存在"));
        }
        List<String> codes = permissionService.loadPermissions(username, null).keySet().stream().sorted().toList();
        return ResponseEntity.ok(Map.of(
                "ok", true,
                "username", username,
                "tenantId", user.getTenantId(),
                "org", user.getOrg(),
                "permissions", codes));
    }
}
