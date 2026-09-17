# 令牌设计：RFC 8693 风格逐跳交换与收窄

> 实现位置：`erp-ai-action/app/auth/token_service.py`（铸造）· `legacy-erp-ap/.../security/AuthFilter.java`（T3 判定）
> 本文回答三个问题：每一跳的令牌长什么样、判定发生在哪一层、为什么收窄是「机制」而不是「约定」。

## 全链路总览

```
用户(浏览器/WorkBuddy/无头脚本)
  │ T1（azp=surface-*）
  ▼
ai-gateway(erp-ai-action) ──IN──▶ hub(erp-ai-hub)
  ▲                                │ T2（azp=erp-ai-hub, act=委托链, scope=场景∩Agent清单）
  └────────────────────────────────┘
  │ T3（azp=erp-ai-action, scope=[单工具], exp 60s）
  ▼
legacy-erp-ap（BO API → PermissionService，三维数据权限）
```

写路径多一跳：审批通过后网关铸 **OT（一次性令牌）**，hub 携 OT 重发，网关验「有效 + 未用 + params_hash 匹配」后放行一次。

## 逐跳 claims

| 跳 | 铸造函数 | 关键 claims | TTL | 谁判定、判什么 |
|---|---|---|---|---|
| 用户→网关 | `mint_t1` | `sub=u-lisi, tid=T-EAST, azp=surface-erp-page\|surface-workbuddy, scope=["chat"], name, org` | 12h | 网关验 SSO/OAuth；T1 只能聊天，不能直接调工具 |
| 网关→hub | `mint_in` | `sub` 不变, `azp=erp-ai-action, aud=erp-ai-hub` | 15min | hub 验共享密钥 + aud；代表「网关背书的用户会话」 |
| hub→网关 | `mint_t2` | `sub` 不变, `azp=erp-ai-hub, act={sub:"agent:ap-copilot", act:{sub:"erp-ai-hub"}}, scope=[场景∩Agent∩请求], scene, agent` | 15min | 网关跑拦截链：注册表→吊销→租户→场景→scope→SoD |
| 网关→Java | `mint_t3` | `azp=erp-ai-action, scope=["ap.invoice.checkValidation"], act` 链保留, `trace_id` | **60s** | Java 只信 `sub+tid`，走存量 `PermissionService`（AI 侧零权限计算） |
| 审批完成 | `mint_ot` | `azp=erp-ai-action, ot_type=one_time, jti`(一次性), `approval_id, params_hash, approver, scope=[单工具]` | 120s | 网关 `verify_ot`：jti 未用 + 未过期 + scope 覆盖 + params_hash 一致 |

公共 claims：`iss=erp-ai-action`、`iat/exp`、`jti`。算法 HS256，密钥 `GW_JWT_SECRET`（compose 注入，网关与 hub 共享）。

## 三条设计原则

### 1) scope 单调递减（逐跳收窄）

```
T1  ["chat"]
T2  ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail", ...]   ← 场景∩Agent清单∩本次请求
T3  ["ap.invoice.checkValidation"]                                    ← 单工具
OT  ["ap.invoice.applyTaxCode"]                                       ← 单工具 + 单参数指纹
```

每一跳的可用权限是上一跳的子集。hub 请求了清单外的工具 → `GW.SCOPE_EXCEEDED`（403）；
Agent 被吊销后既有 T2 下次调用 → `GW.AGENT_REVOKED`（401，即时生效）。判定全部在网关注册表，
**不依赖模型自觉**——提示词注入无法改变拦截结果。

### 2) act 链单调增长（委托链完整留痕）

RFC 8693 Token Exchange 语义：`act` 记录「谁在代表谁行动」。

```json
// T3 的 act：完整委托链，随令牌逐跳携带，进审计与 OTel span
"act": {"sub": "agent:ap-copilot", "act": {"sub": "erp-ai-hub"}}
```

审计五要素中的「Agent」与证据包中的委托链都取自这里——任何一次 BO API 调用都能回答
「哪个用户、经哪个 Agent、由哪个 hub 发起」。

### 3) 权限判定只在存量域（Java）

T3 到达 Java 后，`AuthFilter` 解出 `sub + tid`，走与 ERP 页面**同一个** `PermissionService`
（三维：租户/公司/组织）。AI 链路上任何一层都不做权限计算——这就是「页面 50 条 vs BO API 50 条」
权限对齐（`PermissionParityTest`）的机制来源。租户维度越界一律按 `AP.INVOICE_NOT_FOUND`
处理（不泄露存在性）。

## 拦截链（网关 `/gw/auth/exchange`，按序）

| # | 检查 | 错误码 | 演示 |
|---|---|---|---|
| 1 | Agent 已注册 | `GW.AGENT_NOT_REGISTERED` 401 | scene_4（rogue-agent） |
| 2 | 未被吊销 | `GW.AGENT_REVOKED` 401 | scene_4（吊销即时生效） |
| 3 | 租户一致 | `GW.TENANT_MISMATCH` | tenant_checks 跨租隔离 |
| 4 | 场景存在且启用 | `GW.SCENE_DISABLED` | 场景降级开关 |
| 5 | scope = 请求∩场景∩清单 | `GW.SCOPE_EXCEEDED` 403 | scene_3 |
| 6 | 运行期 SoD 互斥 | `GW.SOD_CONFLICT` | scene_3（税码+付款同持被拒） |

写工具另有一条：网关见规格标记 `x-bo-irreversible: true` → 建 `approval_task` 返回
`GW.APPROVAL_REQUIRED`（retryable，remediation 携 approval_id）。

## 审批 OT 时序（写路径）

```
李四(WorkBuddy/T1) → hub taxcode_graph: suggest → apply(带幂等键)
  → 网关见 irreversible → 建 approval_task(PENDING, params_hash, snapshot)
  → 返回 GW.APPROVAL_REQUIRED → hub interrupt 挂起（PostgresSaver 检查点，零常驻凭据）
王五(WorkBuddy/T1) → GET /gw/approvals → 三要素 + 快照
  → POST /gw/approvals/{id}/decision(approve)
      网关：校验 ap.approval.decide 权限（经存量域）→ 铸 OT(jti 一次性, exp 120s)
  → POST hub /internal/resume {approvalId, oneTimeToken}
      hub 唤醒 → 携 OT 重发（幂等键不变）→ 网关 verify_ot → T3 → Java 同事务落库
      → consume_ot（jti 置已用，无论成败——OT 只能用一次）
```

异常分支独立错误码（可评测）：`GW.APPROVAL_TOKEN_EXPIRED`（OT 无效/已用/过期）、
`GW.APPROVAL_PARAMS_MISMATCH`（审批参数与本次请求不一致）、`GW.APPROVAL_STATE_CONFLICT`
（任务已决定）、`GW.TENANT_MISMATCH`（跨租审批/唤醒）。

## 幂等两层分工

| 层 | 机制 | 键 | 挡什么 |
|---|---|---|---|
| 网关短窗 | TTL 5min 缓存 | hub 按任务步骤生成的 `Idempotency-Key` | 网络重传 |
| 业务侧 | `idempotency_record` 唯一约束，与变更同事务 | 业务键 = 发票号+税码+会计期间 | 业务重复（COMPLETED 返回首次结果 / IN_PROGRESS 返回处理中） |

重复执行同一写请求会命中业务幂等，重放首次结果并引用**原审批单号**（`幂等重放：是`）——
scene_6 与 WorkBuddy E2E 均以此断言。

## 与总纲的对应

总纲第 05 章《AI 应用的鉴权与授权》的全部主张在本仓的落点：
注册中心即访问边界（第 04 幕）、判定不依赖模型自觉（第 03 幕）、逐跳收窄（本表）、
审批即令牌（OT）、幂等两层。演示入口：`python scripts/demo/scene_3.py` / `scene_4.py` / `scene_6.py`。
