package com.erp.ap.seed;

import com.erp.ap.openapi.BulkSeeder;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** 启动期 bulk 种子（5000 条，见 compose ERP_BULK_SEED 开关；幂等）。 */
@Component
@RequiredArgsConstructor
public class DataSeeder implements ApplicationRunner {

    private final JdbcTemplate jdbcTemplate;

    @Value("${erp.bulk-seed}")
    private boolean bulkSeed;

    @Value("${erp.bulk-count:5000}")
    private int bulkCount;

    @Override
    public void run(ApplicationArguments args) {
        if (bulkSeed) {
            int inserted = BulkSeeder.ensureBulk(jdbcTemplate, bulkCount);
            if (inserted > 0) {
                org.slf4j.LoggerFactory.getLogger(DataSeeder.class)
                        .info("[seed] bulk 发票已插入 {} 条（事故端点口径数据）", inserted);
            }
        }
    }
}
