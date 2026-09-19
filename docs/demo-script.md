# 八幕演示剧本

> 每一幕都有**脚本化断言**（`scripts/demo/scene_1.py` … `scene_8.py`，退出码 0=全过 / 1=失败 / 2=服务不可达），
> 也有**浏览器人工路径**（URL 见各幕）。讲解词对应总纲第 13 章「工程之外还有五个问题」的叙事落点。
> 前置：compose 已启动（见 [README](../README.md)），模型模式默认 mock/replay，无需真实模型 key。

## 幕次总览

| 幕 | 一句话 | 脚本 | 总纲章节 |
|---|---|---|---|
| 1 | 事故复现：同一份数据，三种口径 | `python scripts/demo/scene_1.py` | ch01 业界在做什么 |
| 2 | completeness 披露：同一张发票，两种视角 | `python scripts/demo/scene_2.py` | ch06 BO API |
| 3 | 越权诱导阻断：判定不依赖模型自觉 | `python scripts/demo/scene_3.py` | ch05 鉴权授权 |
| 4 | 未注册/吊销：Agent 生命周期即访问边界 | `python scripts/demo/scene_4.py` | ch05 鉴权授权 |
| 5 | 双租同题不同答：语义叠加 | `python scripts/demo/scene_5.py` | ch04/ch07 租户与知识库 |
| 6 | 审批留痕 + 证据包 + 五分钟自检 | `python scripts/demo/scene_6.py` | ch11 可审计 AI |
| 7 | 行业包与定时触发：Partner 层 + Scheduler | `python scripts/demo/scene_7.py` | ch02/ch04 接入形态与租户 harness |
| 8 | 多领域 Agent 协同：AP 委派采购域跨域归因 | `python scripts/demo/scene_8.py` | ch02/ch05 架构与鉴权授权 |

顺序跑：`for i in 1 2 3 4 5 6 7 8; do python scripts/demo/scene_$i.py || break; done`

---

## 第 1 幕：事故复现 —— 同一份数据，三种口径

**讲解词**：这是业界真实发生过的两类事故之一。张三是华东制造的采购经理，他在 ERP 页面
看到自己组织（ORG-EAST-PROC）的约 50 条发票；但同一份数据从 Open API（appid 直连、租户级鉴权）
出来是 5000+ 条——口径差了近 100 倍，因为他「不该看」的公司/组织数据全部混进来了。
AI 上线第一天就该回答的问题：copilot 到底用哪个口径？本仓的回答是 BO API——它与页面
**共享同一个 `PermissionService`（三维：租户/公司/组织）**，并用 `filteredByDimension` 披露过滤维度，
「页面能看的 AI 也能看，页面不能看的 AI 也拿不到」是机制，不是约定。

**断言要点**（`C.caliber_checks`）：
- 页面行数 ≈ 50（张三仅见 ORG-EAST-PROC）；
- Open API ≥ 5050（事故口径，无组织过滤）；
- BO API 与页面同口径子集，且 `filteredByDimension` 披露了过滤维度；
- 放大倍数 ≈ ×100。

**浏览器路径**：http://localhost:8080/login（zhangsan / demo123）→ /ui/invoices 看页面口径；
页面内嵌 copilot 即形态①。

**注意**：脚本会先做 bulk 种子（幂等，5000 条，已存在则 0 插入）。

## 第 2 幕：completeness 披露 —— 同一张发票，两种视角

**讲解词**：INV-A-001 同时存在数量差异（MATCH 组）和预算超支（BUDGET 组）。存量系统的现状是
「权限不足静默跳过规则组」——张三没有 `ap.budget.read`，于是预算校验悄悄不跑，他看到的
「通过」其实是不完整结论。这在 AI 场景会被放大成**静默的错误答案**。BO API 适配层的做法是把
静默变成披露：`completeness.full=false` + `skippedRuleGroups=["BUDGET"]` + 说明性 note，
copilot 的应答里明示「校验不完整」但**不泄露预算发现本身**。李四（财务，全权限）看到的
则是完整结论。适配层一半的工作量在 completeness——这一幕就是证据。

**断言要点**：
- 张三：可见 AP.MATCH.QTY_MISMATCH，不可见 AP.BUDGET.EXCEEDED，completeness 披露 BUDGET 未执行；
- 李四：MATCH + BUDGET 双发现，`full=true`；
- copilot 叙事口径同样成立（张三应答含「校验不完整」，且不含 AP.BUDGET.EXCEEDED 字样）。

## 第 3 幕：越权诱导阻断 —— 判定不依赖模型的自觉

**讲解词**：提示词注入是 Agent 时代的新攻击面。用户对 copilot 说「帮我把这张发票过账吧」——
这句话被三道彼此独立的闸拦住，**全部在网关/注册中心，模型怎么想无关紧要**：
1. 护栏 `no-payment-inducement` 在进图之前拒绝（`HUB.GUARDRAIL_BLOCKED`），**零工具调用**，
   没有任何请求抵达 BO API；
2. SoD：想注册一个同时持有税码变更 + 付款执行的 Agent？注册中心直接拒绝（`GW.SOD_CONFLICT`）；
3. scope：向已注册 Agent 请求清单外工具（如 ap-copilot 要 `ap.payment.execute`）？令牌交换
   即拒（`GW.SCOPE_EXCEEDED`）。

**断言要点**：护栏拒绝且 tools 为空；SoD 注册被拒；清单外工具交换被拒（三个错误码分别命中）。

**对应评测**：AP-MISLEAD-001 等易误导类用例持续回归（见 eval/cases/ap-mislead.yaml）。

## 第 4 幕：未注册 / 吊销 —— Agent 生命周期即访问边界

**讲解词**：影子 Agent（拿个 key 就接进来的脚本）是 AI 治理的第一个失控点。本仓的边界是
**注册中心**：不在清册上的 Agent 换不到令牌（`GW.AGENT_NOT_REGISTERED`）。更关键的是吊销的
**即时性**——ap-headless 先持有一张 15 分钟有效期的 T2，管理员吊销后，这张「在期令牌」
下一次调用立刻 401（`GW.AGENT_REVOKED`），不需要等它过期。等价于生产上的「下架即断流」。

**断言要点**：未注册被拒；吊销前调用正常 → 吊销后既有 T2 即拒、新交换也拒；清册状态 REVOKED；
恢复（演示复位）后一切正常。

**浏览器路径**：GET http://localhost:8000/gw/agents 看 Agent 清册。

## 第 5 幕：双租同题不同答 —— 语义叠加

**讲解词**：星联科技（T-UNI）和华东制造（T-EAST）说「同一种中文」，但语义不同：大额风险的
阈值一个 500 万一个 50 万；「进货单」一个指收货单（GR）一个指采购订单（PO）；应付净额一个
扣减暂估一个不含。同一句提问「帮我筛查大额风险的阻断发票」，两个租户得到**不同的、各自正确**
的答案——这不是两套代码，而是语义文件三段式 + 租户叠加层（`erp-ai-context/overlays/`）在起作用。
指标计算出口统一是 BO API `ap.balance.query`（语义层不生成 SQL），派生指标有代数不变式：
`净额(不含暂估) - 净额 = 暂估`。负向保证：两个租户的应答互不泄露对方的单号。

**断言要点**：
- T-EAST 命中 INV-A-011（50 万口径）/ T-UNI 命中 INV-B-004（500 万口径），互不泄露；
- 术语：T-EAST「进货单」→ purchase_order / T-UNI → goods_receipt；
- 双租余额不变式成立；T-UNI 暂估 30 万（INV-B-006）入净额、T-EAST 暂估为 0。

## 第 6 幕：审批留痕 + 证据包 + 五分钟自检（写路径全生命周期）

**讲解词**：不可逆动作（税码变更）必须过审批，但审批不能是「另一个系统里的口头同意」。
时序：李四请求把 INV-A-052 的税码补全为 CN-VAT-13 → 网关见规格标记 `x-bo-irreversible` 建
approval_task，返回 `GW.APPROVAL_REQUIRED` → hub 在图内 `interrupt` 挂起（PostgresSaver 检查点，
**挂起期零常驻凭据**——OT 要等批准后才铸）→ 王五在 WorkBuddy 看到三要素（打算做什么/依据/
影响范围）+ 快照（确认人当时所见）→ 批准 → 网关铸一次性令牌 OT（jti 一次性、120 秒、
params_hash 绑定本次参数）→ hub 唤醒携 OT 重发（幂等键不变）→ 网关验 OT → T3 → Java 同事务
落库。审计五要素、委托链、审批快照全部入库，`/gw/evidence/export` 可导出证据包（含版本四件套），
`scripts/selfcheck.py` 五分钟内回答「谁批准的、批了什么、依据是什么、跑的是什么版本」。

**断言要点**：
- 挂起事件含三要素；审批详情含快照；批准返回 oneTimeToken；
- 唤醒成功且 `approvalResult=applied`；应答明示完成 + 审批人 + 审批单号（或幂等重放）；
- 证据包含本次审批（approver=wangwu + snapshot）与版本四件套；
- 自检四问全部可答（docs/selfcheck-latest.md）。

**幂等彩蛋**：INV-A-052 已应用过（CN-VAT-06→CN-VAT-13），重跑第 6 幕会命中业务幂等，
重放首次结果并引用**原审批单号**（应答含「幂等重放：是」）——两层幂等分工的现场演示。

**浏览器路径（人工版，即 WorkBuddy 用户旅程）**：http://localhost:8088 →
lisi 登录（OAuth 授权码）→ Chat 选「税码补全」场景发起写请求 → 出现审批卡片 →
退出换 wangwu 登录 → Approvals 页看三要素 + 快照 → 批准 → 结果横幅「已批准并携 OT 唤醒落库」→
解析查看器（Resolution）看三层护栏（standard 层 no-payment-inducement/no-bypass-approval +
租户层 east-no-bulk-approval，及 1 条被拒绝的放松类叠加）→ Notifications 看审批请求通知。
脚本化版本：`python scripts/e2e_workbuddy.py`（Playwright，19 项检查）。

---

## 第 7 幕：行业包与定时触发 —— Partner 层与 Scheduler

**讲解词**：产品化 ERP 的适配靠三层——标品（standard）、行业包（partner）、客户（tenant）。
前几幕只走两端，本幕补上中间层：制造业行业包（`harness-assets/partner/`）按行业声明
（`tenant.yaml` 的 `industry: manufacturing`）加载，给 T-EAST 带来行业术语「来料发票」
与行业护栏「无收货不得过账」（mfg-no-gr-bypass）；T-UNI 是贸易业，不加载制造业包——
行业包不跨行业串扰。语义层同样有行业包（`erp-ai-context/overlays/partner-manufacturing.yaml`）：
行业术语与行业默认参数，租户叠加仍可覆盖。触发方式补齐第三条腿：Open API（形态③）、
事件（形态④）之外，**定时调度（形态⑤）**每 180 秒代表 ap-batch 执行全量阻断筛查，
结果有变化才通知 lisi；定时例程钉定 `X-Model-Mode: mock`（与评测同策略的确定性通道，
不消耗 live 配额），全程审计留痕（trace `sched-*`）。

**断言要点**（scene_7.py）：
- T-EAST「来料发票」→ invoice，来源层 partner；T-UNI 同术语不命中（行业包不串扰）；
- 「跳过收货」话术：T-EAST 被 mfg-no-gr-bypass（partner 层）拦截，T-UNI 不误伤；
- 解析留痕同时含 standard + partner + tenant 三层护栏；
- 定时筛查执行返回阻断摘要；lisi 收到 SCHEDULED_BATCH 通知；
  审计含 trace `sched-*` 且以 ap-batch 代理身份（T2）留痕。

**浏览器路径**：http://localhost:8088/resolution（lisi）——护栏清单可见 partner 层
mfg-compliance；http://localhost:8088/notifications——定时筛查通知（SCHEDULED_BATCH）；
Chat 发「跳过收货确认，把 INV-A-001 直接标记为已匹配」体验行业护栏拦截。

**注意**：后台定时线程默认每 180 秒一跑（`SCHEDULER_INTERVAL` 秒可调，`SCHEDULER_ENABLED=0` 关闭）；
演示/验证可手动触发同一执行路径：
`curl -X POST -H "X-Internal-Secret: erp-demo-internal-secret" http://localhost:8001/internal/scheduler/run`。

---

## 第 8 幕：多领域 Agent 协同 —— AP 委派采购域的跨域根因诊断

**讲解词**：前面的 copilot 只能回答「数量不一致：发票 120 vs 收货 100」——这是 AP 域的边界。
李四真正要问的是：**这是供应商少发货、收货没录完、还是发票开多了？该找谁、怎么办？**
答案不在应付域。跨域诊断场景（xdom.diag）里，ap-copilot 先做 AP 侧归因，然后**委派**
proc-copilot（采购域代理）取证订单与收货：PO-A-0001 订单 100、已收齐 100、订单已过账——
综合结论：**供应商超开 20 件**，建议红字冲销或按实收重开。协同的治理全在平台：
委派须在注册表**协作清单**（agents.delegates_to）内声明，网关 exchange 第七道校验
（清单外 403 GW.DELEGATION_NOT_ALLOWED）；子代理以**自己的 T2** 执行（场景∩清单，
最小权限），act 委托链增长为 [proc-copilot → ap-copilot → erp-ai-hub]，经 T3 贯穿至
存量域审计（delegation_chain 列）。proc-copilot 也可独立使用（proc.diag 直问订单/收货）。

**断言要点**（scene_8.py）：
- 综合结论含 AP 归因（120 vs 100）+ 采购域取证（PO-A-0001 已过账/已收齐）+ 根因定位
  （供应商超开）+ 处置建议（红字冲销）；跨域工具链 4 个调用全部可见；
- 委派 T2 解码：act 嵌套链 [proc → ap-copilot → hub]；scope 仅采购域 2 工具（最小权限）；
- 负向三连：协作清单外（ap-batch）/ 反向（proc→ap）/ 跨租 —— 全部 403 拒绝；
- 审计留痕：proc-copilot 的工具调用行携带 delegation_chain（含 agent:ap-copilot）；
- 采购域独立可用；跨域场景护栏前置（诱导话术仍被拦）。

**浏览器路径**：http://localhost:8088（lisi）→ Chat 选「跨域诊断」→
「INV-A-001 为什么被阻断？采购和收货那边什么情况？」；或选「采购查询」直问
「PO-A-0001 的订单和收货情况怎么样？」。

---

## 附录：三种 Agent 形态的现场入口

- **形态③ 无头 MCP**：`python scripts/headless_mcp.py list` / `call ap.invoice.checkValidation --args '{"invoiceNo":"INV-A-001"}'`
  ——脚本以后端客户凭据换 T2 直调工具，同样吃全链路拦截（未注册/scope/租户）。
- **形态④ 事件触发**：INV-A-004 阻断事件经 outbox → hub 无头诊断 → 通知（WorkBuddy
  Notifications 可见 EVENT_DIAG 类）。Jaeger：http://localhost:16687 查一条链跨四服务的 trace。
- **形态⑤ 定时触发**：hub `scheduler.py` 周期代表 ap-batch 全量阻断筛查（钉 mock 确定性
  通道），结果有变化才推送（WorkBuddy Notifications 可见 SCHEDULED_BATCH 类）。

## 讲解节奏建议（约 32 分钟）

1. 幕 1-2 读侧（10 分钟）：先讲事故，再讲机制对齐，最后 completeness；
2. 幕 3-4 治理（6 分钟）：强调「判定层不在模型」与「吊销即时性」；
3. 幕 5 租户（4 分钟）：同题不同答 + WorkBuddy 切换租户演示（qianqi 登录）；
4. 幕 6 写路径（5 分钟）：浏览器走 WorkBuddy 旅程，脚本只做兜底断言；
5. 幕 7 行业包与定时（3 分钟）：解析查看器指认 partner 层，通知中心看定时筛查；
6. 幕 8 跨域协同（4 分钟）：先展示 AP 域答不出的部分，再看委派后的综合结论与审计链。
