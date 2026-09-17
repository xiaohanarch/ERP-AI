-- 评测确定性标的（种子只增不改）：
--   INV-A-051：税码建议「读侧」锚点 —— 与 INV-A-003 同构（供应商 1 江苏，常用税码
--              CN-VAT-13，发票税码 CN-VAT-06 不符 -> TAX WARN），但评测写路径永不
--              触碰它，保证 AP.TAX.CODE_SUGGESTED 发现长期稳定可断言。
--   INV-A-052：税码补全「写路径」评测标的 —— 评测用例（审批/幂等/权限拒绝）在此
--              落库，避免消耗 INV-A-003（演示剧本的主角，需保持"待补全"初始状态）。
-- 无 PO/GR（MATCH 组静默通过，同 INV-A-005..050 模式），ORG-EAST-PROC（张三可见）。
INSERT INTO invoice (invoice_no, supplier_id, po_id, gr_id, org, company, tenant_id,
                     amount_cny, tax_code, status, validation_status, is_accrual, period, paid_cny) VALUES
('INV-A-051', 1, NULL, NULL, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST',
 5000.00, 'CN-VAT-06', 'POSTED', 'WARNED', FALSE, '2026-09', 0),
('INV-A-052', 1, NULL, NULL, 'ORG-EAST-PROC', '华东制造有限公司', 'T-EAST',
 5200.00, 'CN-VAT-06', 'POSTED', 'WARNED', FALSE, '2026-09', 0);
