# 验证报告（verification report）

- 生成时间：2026-09-17 13:31:48
- 版本戳：spec `1.0.0` / ruleset `AP-RS-1.2.0` / seed `ap-seed-1.0.0` / 语义 `ap-sem-1.0.0` / 模型 `mock-scene-model`（mock）
- 结论：**全部体系绿**

## 一、总览

| 检验体系 | 结果 | 判定 |
|---|---|---|
| 全量评测（50 锚点用例） | 50/50 通过，耗时 16.2s | ✅ |
| 多租六项检验 | 37/37 通过 | ✅ |
| 漂移检测 | 检出 2 处预埋漂移（全部检出） | ✅ |
| 五分钟自检（四问） | 全部可答（docs/selfcheck-latest.md） | ✅ |
| 事故三口径断言 | 页面 ~50 / Open API ≥5050（~100 倍）/ BO 同权限口径 | ✅ |

## 二、评测指标 vs 目标

| 指标 | 实测 | 目标 | 判定 |
|---|---|---|---|
| 工具正确性 | 1.0 | ≥ 0.98 | ✅ |
| 参数正确性 | 1.0 | ≥ 0.95 | ✅ |
| 最大步数 | 2 | ≤ 4 | ✅ |
| 禁调违规 | 0 | = 0 | ✅ |
| 零容忍失败（AP-COMP/AP-HALLU） | 无 | = 0 | ✅ |

## 三、评测用例六类分布

| 类别 | 通过/总数 |
|---|---|
| AP-COMP | 8/8 |
| AP-DIAG | 10/10 |
| AP-HALLU | 4/4 |
| AP-MISLEAD | 6/6 |
| AP-PERM | 7/7 |
| AP-TOOL | 15/15 |

## 四、多租六项明细

- **A0 叠加**：10/10 通过
- **术语叠加**：3/3 通过
- **派生指标**：6/6 通过
- **三层解析**：6/6 通过
- **跨租隔离**：5/5 通过
- **成本归集**：7/7 通过

## 五、漂移检测明细（预埋漂移必须检出）

- [FIELD_DRIFT/HIGH] 派生字段 Invoice.accrual_flag 与元数据现状不符（疑似对应 is_accrual）
- [RULE_DRIFT/MEDIUM] 语义层引用的规则 AP.TAX.RATE_CHECK 在存量规则清单中不存在（规则已删除或改名）

- 基线：ruleset `AP-RS-1.2.0` / seed `ap-seed-1.0.0` / 语义 `ap-sem-1.0.0`；检查字段 1 个、规则 6 条

## 六、事故三口径对照（张三，T-EAST）

| 口径 | 行数 | 权限语义 |
|---|---|---|
| ERP 页面（会话 + 组织过滤） | 52 | 张三仅见 ORG-EAST-PROC |
| Open API（appid 直连，租户级） | 5054 | **事故口径**：无组织过滤，全租可见 |
| BO API（T3，与页面同权限组件） | 10（阻断子集） | 同组织口径 + filteredByDimension 披露 |

- BO API 披露维度：['tenant', 'org']；命中组织：['ORG-EAST-PROC']；命中单据：INV-A-001, INV-A-004, INV-A-007, INV-A-011, INV-A-013, INV-A-019, INV-A-023, INV-A-031…
- 断言：页面口径约 50 条（会话 + 组织过滤） ✓；Open API 口径 ≥5050 条（租户级事故端点） ✓；事故放大倍数 ~100 倍 ✓；BO API 与页面同组织口径（仅 ORG-EAST-PROC） ✓；BO API 命中数不超过页面口径 ✓；BO API 披露过滤维度（含 org） ✓

---
生成物：`docs/verification-report.md`（本文件）、`docs/selfcheck-latest.md`、`eval/reports/full-latest.{json,md}`、`eval/reports/tenant-checks-latest.json`。
