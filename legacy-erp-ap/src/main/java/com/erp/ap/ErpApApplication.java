package com.erp.ap;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 存量 ERP 应付（AP）模块仿真入口（appid: erp-ap）。
 *
 * 同一服务暴露三类口径 + MCP：
 *  - UI API   ：页面会话 + 三维数据权限（页面 50 条口径）
 *  - BO API   ：双主体令牌 T3 + 同一 PermissionService（AI 唯一合规入口）
 *  - Open API ：appid 直连、租户级（历史事故口径：5000 条）
 *  - MCP      ：工具定义由 boapi-spec/bo-ap.yaml 构建期生成（规格即工具）
 */
@SpringBootApplication
public class ErpApApplication {
    public static void main(String[] args) {
        SpringApplication.run(ErpApApplication.class, args);
    }
}
