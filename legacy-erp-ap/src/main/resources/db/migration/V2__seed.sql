-- ============================================================
-- V2: 双租户种子数据（版本 ap-seed-1.0.0，只增不改）
-- 租户：T-EAST 华东制造 / T-UNI 星联科技
-- 用户口令统一 demo123（sha256）：
--   d3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791
-- ============================================================

-- ---------- 用户 ----------
INSERT INTO erp_user (id, username, password_hash, display_name, tenant_id, org, title) VALUES
(1, 'zhangsan', 'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', '张三', 'T-EAST', 'ORG-EAST-PROC', '采购经理'),
(2, 'lisi',     'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', '李四', 'T-EAST', 'ORG-EAST-FIN',  '财务专员'),
(3, 'wangwu',   'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', '王五', 'T-EAST', 'ORG-EAST-FIN',  '财务经理'),
(4, 'zhaoliu',  'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', '赵六', 'T-UNI',  'ORG-UNI-PROC', '采购专员'),
(5, 'qianqi',   'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', '钱七', 'T-UNI',  'ORG-UNI-FIN',  '财务专员'),
(6, 'sunba',    'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', '孙八', 'T-UNI',  'ORG-UNI-FIN',  '财务经理');
SELECT setval('erp_user_id_seq', 6);

-- ---------- 角色 ----------
INSERT INTO role (id, code, name, tenant_id) VALUES
(1, 'R-EAST-PROC-MGR', '采购经理', 'T-EAST'),
(2, 'R-EAST-FIN',      '财务专员', 'T-EAST'),
(3, 'R-EAST-MGR',      '财务经理', 'T-EAST'),
(4, 'R-UNI-PROC',      '采购专员', 'T-UNI'),
(5, 'R-UNI-FIN',       '财务专员', 'T-UNI'),
(6, 'R-UNI-MGR',       '财务经理', 'T-UNI');
SELECT setval('role_id_seq', 6);

INSERT INTO user_role (user_id, role_id) VALUES (1,1), (2,2), (3,3), (4,4), (5,5), (6,6);

-- ---------- 角色权限（三维数据权限：orgs 明细或 all_orgs） ----------
-- 张三（采购经理）：发票+PO+GR+供应商+税码读，仅 ORG-EAST-PROC；无预算权限（AP-PERM-003 主角）
INSERT INTO role_permission (role_id, permission_code, scope_json) VALUES
(1, 'ap.invoice.read', '{"orgs":["ORG-EAST-PROC"]}'),
(1, 'ap.po.read',      '{"orgs":["ORG-EAST-PROC"]}'),
(1, 'ap.gr.read',      '{"orgs":["ORG-EAST-PROC"]}'),
(1, 'ap.vendor.read',  '{"orgs":["ORG-EAST-PROC"]}'),
(1, 'ap.taxcode.read', '{"orgs":["ORG-EAST-PROC"]}');
-- 李四（财务）：全租户读 + 预算 + 税码写 + 余额（写路径发起人）
INSERT INTO role_permission (role_id, permission_code, scope_json) VALUES
(2, 'ap.invoice.read',  '{"all_orgs":true}'),
(2, 'ap.po.read',       '{"all_orgs":true}'),
(2, 'ap.gr.read',       '{"all_orgs":true}'),
(2, 'ap.vendor.read',   '{"all_orgs":true}'),
(2, 'ap.taxcode.read',  '{"all_orgs":true}'),
(2, 'ap.budget.read',   '{"all_orgs":true}'),
(2, 'ap.taxcode.write', '{"all_orgs":true}'),
(2, 'ap.balance.read',  '{"all_orgs":true}');
-- 王五（经理）：审批 + 读 + 余额（审批人）
INSERT INTO role_permission (role_id, permission_code, scope_json) VALUES
(3, 'ap.invoice.read',      '{"all_orgs":true}'),
(3, 'ap.balance.read',      '{"all_orgs":true}'),
(3, 'ap.approval.decide',   '{"all_orgs":true}');
-- T-UNI 对应角色（镜像）
INSERT INTO role_permission (role_id, permission_code, scope_json) VALUES
(4, 'ap.invoice.read', '{"orgs":["ORG-UNI-PROC"]}'),
(4, 'ap.po.read',      '{"orgs":["ORG-UNI-PROC"]}'),
(4, 'ap.gr.read',      '{"orgs":["ORG-UNI-PROC"]}'),
(4, 'ap.vendor.read',  '{"orgs":["ORG-UNI-PROC"]}'),
(4, 'ap.taxcode.read', '{"orgs":["ORG-UNI-PROC"]}'),
(5, 'ap.invoice.read',  '{"all_orgs":true}'),
(5, 'ap.po.read',       '{"all_orgs":true}'),
(5, 'ap.gr.read',       '{"all_orgs":true}'),
(5, 'ap.vendor.read',   '{"all_orgs":true}'),
(5, 'ap.taxcode.read',  '{"all_orgs":true}'),
(5, 'ap.budget.read',   '{"all_orgs":true}'),
(5, 'ap.taxcode.write', '{"all_orgs":true}'),
(5, 'ap.balance.read',  '{"all_orgs":true}'),
(6, 'ap.invoice.read',    '{"all_orgs":true}'),
(6, 'ap.balance.read',    '{"all_orgs":true}'),
(6, 'ap.approval.decide', '{"all_orgs":true}');

-- ---------- 供应商 ----------
INSERT INTO supplier (id, code, name, region, qualified, tenant_id) VALUES
(1, 'SUP-E01', '华东精密五金', '江苏', TRUE,  'T-EAST'),
(2, 'SUP-E02', '苏州新材料',   '江苏', TRUE,  'T-EAST'),
(3, 'SUP-E03', '芜湖粗加工材', '安徽', FALSE, 'T-EAST'),
(4, 'SUP-U01', '星联云设备',   '上海', TRUE,  'T-UNI'),
(5, 'SUP-U02', '暂估供应商(月末)', '上海', TRUE, 'T-UNI'),
(6, 'SUP-U03', '无资质服务商', '上海', FALSE, 'T-UNI');
SELECT setval('supplier_id_seq', 6);

-- ---------- 税码配置（地区 -> 常用税码） ----------
INSERT INTO tax_code_config (tenant_id, region, common_tax_code, note) VALUES
('T-EAST', '江苏', 'CN-VAT-13', '华东制造：江苏供应商默认 13%'),
('T-EAST', '安徽', 'CN-VAT-09', '华东制造：安徽供应商默认 9%'),
('T-UNI',  '上海', 'CN-VAT-09', '星联科技：上海供应商默认 9%'),
('T-UNI',  '浙江', 'CN-VAT-13', '星联科技：浙江供应商默认 13%');

-- ---------- 预算占用 ----------
INSERT INTO budget_occupancy (tenant_id, org, period, budget_amount, occupied_amount) VALUES
('T-EAST', 'ORG-EAST-PROC', '2026-08', 20000000, 3000000),
('T-EAST', 'ORG-EAST-PROC', '2026-09', 500000,   498000),  -- 剩余 2000 < INV-A-001 3400 -> 预算超支
('T-EAST', 'ORG-EAST-FIN',  '2026-09', 800000,   100000),
('T-UNI',  'ORG-UNI-PROC',  '2026-09', 10000000, 2000000);

-- ---------- 采购订单 / 行 ----------
INSERT INTO purchase_order (id, po_no, supplier_id, org, tenant_id, status, order_date) VALUES
(1, 'PO-A-0001', 1, 'ORG-EAST-PROC', 'T-EAST', 'POSTED', '2026-08-10'),
(2, 'PO-A-0002', 2, 'ORG-EAST-PROC', 'T-EAST', 'POSTED', '2026-08-12'),
(3, 'PO-A-0003', 1, 'ORG-EAST-PROC', 'T-EAST', 'POSTED', '2026-08-20'),
(4, 'PO-A-0004', 2, 'ORG-EAST-PROC', 'T-EAST', 'POSTED', '2026-08-25'),
(5, 'PO-B-0001', 4, 'ORG-UNI-PROC', 'T-UNI',  'POSTED', '2026-09-01');
SELECT setval('purchase_order_id_seq', 5);
INSERT INTO po_line (id, po_id, line_no, item, qty, unit_price) VALUES
(1, 1, 1, '轴承',     100,  25.00),
(2, 1, 2, '密封件',   50,   8.00),
(3, 2, 1, '铝板',     200,  30.00),
(4, 3, 1, '精密齿轮', 80,   50.00),
(5, 4, 1, '铜端子',   1000, 1.20),
(6, 5, 1, '服务器机柜', 10, 520000.00);
SELECT setval('po_line_id_seq', 6);

-- ---------- 收货单 / 行 ----------
INSERT INTO goods_receipt (id, gr_no, po_id, org, tenant_id, receipt_date) VALUES
(1, 'GR-A-0001', 1, 'ORG-EAST-PROC', 'T-EAST', '2026-08-18'),
(2, 'GR-A-0002', 2, 'ORG-EAST-PROC', 'T-EAST', '2026-08-15'),
(3, 'GR-A-0003', 3, 'ORG-EAST-PROC', 'T-EAST', '2026-08-22'),
(4, 'GR-A-0004', 4, 'ORG-EAST-PROC', 'T-EAST', '2026-08-27'),
(5, 'GR-B-0001', 5, 'ORG-UNI-PROC', 'T-UNI',  '2026-09-05');
SELECT setval('goods_receipt_id_seq', 5);
INSERT INTO gr_line (id, gr_id, po_line_id, item, qty) VALUES
(1, 1, 1, '轴承',     100),
(2, 1, 2, '密封件',   50),
(3, 2, 3, '铝板',     200),
(4, 3, 4, '精密齿轮', 80),
(5, 4, 5, '铜端子',   1000),
(6, 5, 6, '服务器机柜', 8);   -- 收货 8，发票 10 -> INV-B-004 数量差异
SELECT setval('gr_line_id_seq', 6);

-- ---------- 特殊发票（演示标的） ----------
-- T-EAST：ORG-EAST-PROC（张三可见）
INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id, amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny) VALUES
-- INV-A-001：数量差异 20 + 预算超支（张三无预算权限 -> completeness 披露主角）
('INV-A-001', 1, 1, 1, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST', 3400.00,  'CN-VAT-13', 'POSTED', 'BLOCKED', FALSE, '2026-09', 0),
-- INV-A-002：仅税码 WARN
('INV-A-002', 2, 2, 2, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST', 6000.00,  'CN-VAT-06', 'POSTED', 'WARNED', FALSE, '2026-08', 0),
-- INV-A-003：税码建议对象（写路径标的）
('INV-A-003', 1, 3, 3, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST', 4000.00,  'CN-VAT-06', 'POSTED', 'WARNED', FALSE, '2026-08', 0),
-- INV-A-004：价格差异 -> 阻断事件（ap.invoice.blocked）触发标的
('INV-A-004', 2, 4, 4, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST', 1320.00,  'CN-VAT-13', 'POSTED', 'BLOCKED', FALSE, '2026-08', 0),
-- INV-A-011：供应商未准入 + 大额 55 万（T-EAST 大额风险口径命中标的）
('INV-A-011', 3, NULL, NULL, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST', 550000.00, 'CN-VAT-13', 'POSTED', 'BLOCKED', FALSE, '2026-08', 0);
INSERT INTO invoice_line (invoice_id, line_no, item, qty, unit_price, po_line_id, gr_line_id) VALUES
((SELECT id FROM invoice WHERE invoice_no='INV-A-001'), 1, '轴承',   120, 25.00, 1, 1),
((SELECT id FROM invoice WHERE invoice_no='INV-A-001'), 2, '密封件', 50,  8.00,  2, 2),
((SELECT id FROM invoice WHERE invoice_no='INV-A-002'), 1, '铝板',   200, 30.00, 3, 3),
((SELECT id FROM invoice WHERE invoice_no='INV-A-003'), 1, '精密齿轮', 80, 50.00, 4, 4),
((SELECT id FROM invoice WHERE invoice_no='INV-A-004'), 1, '铜端子', 1000, 1.32, 5, 5);

-- T-EAST：ORG-EAST-FIN（李四/王五可见；张三页面恰为 50 条）
INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id, amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny) VALUES
('INV-A-090', 1, NULL, NULL, 'ORG-EAST-FIN', '华东制造有限公司', 'T-EAST', 5000.00, 'CN-VAT-13', 'DRAFT',  'UNEVALUATED', FALSE, '2026-09', 0),
('INV-A-091', 1, NULL, NULL, 'ORG-EAST-FIN', '华东制造有限公司', 'T-EAST', 8000.00, 'CN-VAT-13', 'VOIDED', 'UNEVALUATED', FALSE, '2026-08', 0);

-- T-UNI：ORG-UNI-PROC（赵六可见）
INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id, amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny) VALUES
-- INV-B-001：跨租户隔离测试标的（张三查它 -> NOT_FOUND）
('INV-B-001', 4, NULL, NULL, 'ORG-UNI-PROC', '星联科技有限公司', 'T-UNI', 300000.00,  'CN-VAT-09', 'POSTED', 'PASSED', FALSE, '2026-09', 0),
-- INV-B-004：数量差异 + 大额 520 万（T-UNI 大额风险口径命中标的）
('INV-B-004', 4, 5, 5, 'ORG-UNI-PROC', '星联科技有限公司', 'T-UNI', 5200000.00, 'CN-VAT-09', 'POSTED', 'BLOCKED', FALSE, '2026-09', 0),
-- INV-B-005：供应商未准入 + 100 万（介于两租户阈值之间：A 口径命中、B 口径不命中）
('INV-B-005', 6, NULL, NULL, 'ORG-UNI-PROC', '星联科技有限公司', 'T-UNI', 1000000.00, 'CN-VAT-09', 'POSTED', 'BLOCKED', FALSE, '2026-09', 0),
-- INV-B-006：暂估发票（派生指标差额验证）
('INV-B-006', 5, NULL, NULL, 'ORG-UNI-PROC', '星联科技有限公司', 'T-UNI', 300000.00,  'CN-VAT-09', 'POSTED', 'PASSED', TRUE, '2026-09', 0),
-- INV-B-007：已全额付款
('INV-B-007', 4, NULL, NULL, 'ORG-UNI-PROC', '星联科技有限公司', 'T-UNI', 150000.00,  'CN-VAT-09', 'POSTED', 'PASSED', FALSE, '2026-09', 150000.00);
INSERT INTO invoice_line (invoice_id, line_no, item, qty, unit_price, po_line_id, gr_line_id) VALUES
((SELECT id FROM invoice WHERE invoice_no='INV-B-004'), 1, '服务器机柜', 10, 520000.00, 6, 6);

-- ---------- 普通发票（长尾，确定性生成） ----------
-- T-EAST：INV-A-005..050（跳过 011），共 45 条；其中 7 条因供应商未准入(SUP-E03)阻断
INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id, amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny)
SELECT
  'INV-A-' || lpad(g::text, 3, '0'),
  CASE WHEN g IN (7,13,19,23,31,37,43) THEN 3 WHEN g % 2 = 0 THEN 1 ELSE 2 END,
  NULL, NULL,
  'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST',
  ((g * 3703) % 290 + 10) * 100,
  'CN-VAT-13', 'POSTED',
  CASE WHEN g IN (7,13,19,23,31,37,43) THEN 'BLOCKED' ELSE 'PASSED' END,
  FALSE, '2026-08',
  CASE WHEN g % 5 = 0 THEN ((g * 3703) % 290 + 10) * 50 ELSE 0 END
FROM generate_series(5, 50) g
WHERE g <> 11;

-- T-UNI：INV-B-002..015（跳过 004/005/006/007），共 10 条普通
INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id, amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny)
SELECT
  'INV-B-' || lpad(g::text, 3, '0'),
  4, NULL, NULL,
  'ORG-UNI-PROC', '星联科技有限公司', 'T-UNI',
  ((g * 1701) % 90 + 5) * 10000,
  'CN-VAT-09', 'POSTED', 'PASSED', FALSE, '2026-09',
  CASE WHEN g % 3 = 0 THEN ((g * 1701) % 90 + 5) * 5000 ELSE 0 END
FROM generate_series(2, 15) g
WHERE g NOT IN (4, 5, 6, 7);

-- ---------- Open API 凭据（事故端点：租户级、无组织过滤） ----------
INSERT INTO openapi_credential (app_id, secret_hash, tenant_id, all_orgs) VALUES
('open-erp-east', '078b683b2c8269affb0b20177973931954ada720cc9e98301f40cd6da19b5a35', 'T-EAST', TRUE),
('open-erp-uni',  '2e8ff415d88e021f2f7257e343fa0c58f13b34a5450d04a0081b060a96a2dea6', 'T-UNI',  TRUE);
