package com.erp.ap.openapi;

import org.springframework.jdbc.core.JdbcTemplate;

/** bulk 发票种子（仅头表，分布于工厂组织 -> 页面口径不可见、Open API 可见）。 */
public final class BulkSeeder {

    static final String PREFIX = "INV-BULK-";

    private BulkSeeder() {
    }

    /** 幂等插入：返回本次实际插入条数。 */
    public static int ensureBulk(JdbcTemplate jdbc, int target) {
        Number existing = (Number) jdbc.queryForObject(
                "SELECT count(*) FROM invoice WHERE invoice_no LIKE '" + PREFIX + "%'", Number.class);
        int have = existing == null ? 0 : existing.intValue();
        if (have >= target) {
            return 0;
        }
        int toInsert = target - have;
        String[] orgs = {"ORG-EAST-PLT1", "ORG-EAST-PLT2", "ORG-EAST-PLT3"};
        String sql = "INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id, "
                + "amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny) "
                + "VALUES (?, ?, NULL, NULL, ?, '华东制造有限公司', 'T-EAST', ?, 'CN-VAT-13', 'POSTED', 'UNEVALUATED', FALSE, '2026-09', 0)";
        int batchSize = 500;
        int done = 0;
        while (done < toInsert) {
            int chunk = Math.min(batchSize, toInsert - done);
            var args = new java.util.ArrayList<Object[]>();
            for (int i = 0; i < chunk; i++) {
                int seq = have + done + i + 1;
                args.add(new Object[]{
                        PREFIX + String.format("%05d", seq),
                        (seq % 2 == 0) ? 1L : 2L,
                        orgs[seq % 3],
                        (long) ((seq * 3703) % 900 + 100)});
            }
            jdbc.batchUpdate(sql, args);
            done += chunk;
        }
        return done;
    }
}
