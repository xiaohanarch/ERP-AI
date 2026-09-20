# 五分钟自检报告

- 生成时间：2026-09-19 21:10:32
- 服务健康：全部可达
- 版本戳：spec `1.2.0` / ruleset `AP-RS-1.2.0` / seed `ap-seed-1.0.0` / 语义 `ap-sem-1.1.0` / 模型 `glm-5.3`（live）

## Q1 谁在用？（Agent 清册）

| Agent | 租户 | 状态 | 工具数 | 负责人 |
|---|---|---|---|---|
| ap-headless | T-EAST | 在册 | 5 | zhangsan |
| event-diag | T-EAST | 在册 | 2 | lisi |
| uni-copilot | T-UNI | 在册 | 13 | qianqi |
| ap-batch | T-EAST | 在册 | 6 | lisi |
| ap-copilot | T-EAST | 在册 | 13 | lisi |
| uni-batch | T-UNI | 在册 | 6 | qianqi |
| proc-copilot | T-EAST | 在册 | 2 | lisi |

（共 7 个，全部在册）

## Q2 刚才发生了什么？（审计五要素·最近 15 条）

| 时间 | 租户 | 用户 | Agent | 动作 | 结果 | 错误码 | 审批 |
|---|---|---|---|---|---|---|---|
| 2026-09-20T04:10:31 | - | - | - | agent.roster.view | SUCCESS | - | - |
| 2026-09-20T04:10:28 | T-UNI | qianqi | agent:uni-copilot | ap.invoice.checkValidation | SUCCESS | - | - |
| 2026-09-20T04:10:28 | T-UNI | qianqi | - | model_call | SUCCESS | - | - |
| 2026-09-20T04:10:28 | T-EAST | lisi | agent:ap-copilot | ap.invoice.checkValidation | SUCCESS | - | - |
| 2026-09-20T04:10:28 | T-EAST | lisi | - | model_call | SUCCESS | - | - |
| 2026-09-20T04:10:27 | T-UNI | zhaoliu | agent:uni-copilot | ap.invoice.checkValidation | ERROR | AP.INVOICE_NOT_FOUND | - |
| 2026-09-20T04:10:27 | T-UNI | zhaoliu | - | model_call | SUCCESS | - | - |
| 2026-09-20T04:10:27 | T-EAST | zhangsan | agent:ap-copilot | ap.invoice.checkValidation | ERROR | AP.INVOICE_NOT_FOUND | - |
| 2026-09-20T04:10:27 | T-EAST | zhangsan | - | model_call | SUCCESS | - | - |
| 2026-09-20T04:10:26 | T-UNI | qianqi | agent:uni-copilot | ap.invoice.checkValidation | SUCCESS | - | - |
| 2026-09-20T04:10:26 | T-UNI | qianqi | - | model_call | SUCCESS | - | - |
| 2026-09-20T04:10:26 | T-EAST | lisi | agent:ap-copilot | ap.invoice.getMatchDetail | SUCCESS | - | - |
| 2026-09-20T04:10:26 | T-EAST | lisi | agent:ap-copilot | ap.invoice.checkValidation | SUCCESS | - | - |
| 2026-09-20T04:10:26 | T-EAST | lisi | - | model_call | SUCCESS | - | - |
| 2026-09-20T04:10:25 | T-UNI | qianqi | agent:uni-batch | semantic.metric.get | SUCCESS | - | - |

## Q3 有没有异常？（拦截与拒绝分布）

- 近 500 条审计中拒绝/错误 18 条：
  - `AP.INVOICE_NOT_FOUND` × 12
  - `AP.PERMISSION_DENIED` × 4
  - `AP.INVOICE_IN_DRAFT` × 2
- 其中护栏拦截（诱导/越权话术）0 条 —— 拦截即机制生效，非事故。
- 评测锚点：full 档 50/50 通过（全绿）

## Q4 花了多少钱？（双租成本与对账）

| 租户 | 调用数 | token 合计 | 审计对账 |
|---|---|---|---|
| T-EAST | 1224 | 163,041 | 一致 |
| T-UNI | 270 | 32,743 | 一致 |

---
结论：四问 全部可答。
