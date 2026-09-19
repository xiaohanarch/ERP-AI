# 14 条架构判断 × 本仓对照（AI-Native 对齐分析）

> **背景**：以《AI 原生重构 ERP 选型逻辑：外挂式 AI 时代走向落幕》（老丁，2026-08-24）为参照系，
> 逐条检验本仓（ERP-Demo）的 14 条架构判断：哪些已实现且已验证、哪些部分实现、哪些存在
> 表述张力、哪些是空白。
> **版本**：初版分析 2026-09-18；同日补齐两个 P0 缺口（Partner 行业包 + Scheduler 定时触发，
> 见 [第五节](#五p0-补齐记录2026-09-18)与 `python scripts/demo/scene_7.py`），本文为补齐后版本。

---

## 〇、参照系：AI 原生的可检验判据

参照文章的核心贡献不是口号，而是一组**可检验的判据**：

> 二者的差别不在于「能不能生成单据」，而在于 AI 执行业务动作时，**是否天然复用 ERP 内核的
> 权限、业务校验、风险拦截与审计追溯能力**。

- 四维对比：架构定位 / 权限与校验 / 风险管控 / 业务闭环；
- 代驾类比：外挂 = 车外遥控（自带一套权限），原生 = 坐进驾驶室（复用原车钥匙/刹车/行车记录仪）；
- 选型五条：真原生 vs 套壳 / 幻觉管控 / 编排与本体 / 异构兼容 / 务实路径；
- **关键澄清**：文章把「不推倒存量、独立智能体底座封装对接」定义为 AI 原生的合法路线
  （底座优先），与内核重构（用友 BIP6 路线）并列——**拓扑上旁挂 ≠ 外挂**，判据是管控是否复用。

14 条判断本质上是这套判据的工程化展开，且多处比文章更进一步（Ontology 来源、租户隔离、
人的四阶段，文章均未涉及）。

## 一、总对照表

| # | 判断 | 结论 | 本仓证据 |
|---|---|---|---|
| 1 | AI-Native 而非 ERP+AI | ✅ 一致 | 底座优先路线：AI 动作全走 T2/T3 令牌 + BO 合同 + Java 原生校验/幂等/审计，无平行权限体系 |
| 2 | 传统 ERP = SoR + 确定性执行 | ✅ 一致 | legacy-erp-ap 即此定位：`@Transactional`、幂等重放、稳定错误码（评测断言）；AI 不绕过 |
| 3 | AI 是 ERP 内生组成部分 | ✅ 一致（底座式内生） | 三口径验证证明 BO 工具与页面同权限组件（见张力 A 的表述建议） |
| 4 | Ontology 是统一语义模型 + 逻辑核心 | ⚠️ 半一致 | 语义层是统一语义模型 ✓；「逻辑核心」只达成弱形式（见张力 B 的分阶段表述） |
| 5 | Metadata 是 Ontology 的输入/来源 | ✅ 一致且超预期 | 三段式（投影/增量/原生）+ 漂移检测把这条做成**可检验不变式** |
| 6 | 多领域 Agent + 协同组合 | ✅ 一致（**P1 已补齐**） | 采购域最小切片（proc.po.getDetail / proc.gr.listForPo）+ 跨域场景 xdom.diag：ap-copilot 委派 proc-copilot（协作清单 + act 链增长 + 子代理最小权限 T2），scene_8 |
| 7 | Agent→Capability/API→Microservice→Transaction | ✅ 一致 | hub 场景图→网关 MCP 代理→Java BO API→事务；Jaeger 全链 trace；intro.html 顶部链路动画即此链 |
| 8 | 流程以预定义为主，不要求自适应 | ✅ 一致 | LangGraph 图静态装配，模型只按动作契约填意图/参数，不自主规划路径 |
| 9 | AI 可理解使用规则、不可修改 | ✅ 一致且已验证 | 护栏三层解析前置拦截（AP-MISLEAD 6/6）、`semantic.operation.explain` 供理解、无任何写规则的模型工具 |
| 10 | Open API / Event / Scheduler 触发 | ✅ 一致（**P0 已补齐**） | Open API ✓（形态③ headless）、Event ✓（形态④ outbox→event-diag→通知）、Scheduler ✓（形态⑤ 定时筛查，scene_7） |
| 11 | 人：执行者→确认者→例外处理者→监督者 | ✅ 一致且产品化 | 确认者=审批台（三要素+快照+params_hash）、例外处理者=挂起/唤醒、监督者=解析查看器+审计五要素+四问自检+成本对账 |
| 12 | Agent 先协同、终局替换部分传统执行 | ✅ 当前阶段一致 | 现处「协同」阶段；管控面的执行端无关性是为终局预留的对冲（见张力 C） |
| 13 | 标品 core + Metadata/Ontology/配置适配 | ✅ 一致（**P0 已补齐行业维度**） | 租户叠加（阈值/术语/指标口径/护栏）+ 行业包（Partner 层：制造业术语/护栏/行业默认参数，按行业声明匹配不串扰）；配置仍为文件级（无配置界面） |
| 14 | SaaS 标品层/租户层隔离，API/Message 扩展 | 🟡 API✓ Message✗ | 跨租隔离 5/5、成本双租对账、三层解析隔离 ✓；Message 扩展通道未体现 |

## 二、三个张力点（需要理念层面表态的地方）

### A. 「AI 内生」（观点 3）vs 旁挂拓扑 —— 不冲突，但要钉死表述

本仓拓扑是「Python 底座 + Java 存量」两套栈。按字面最强读法（AI 下沉进 ERP 内核，BIP6 路线），
本仓**不是**那条——也不能是：本仓的前提就是存量不动。但按文章判据，本仓恰是「内生」的
**可验证形态**：事故三口径对照（页面 ~50 / Open API ≥5050 / BO 10 条同组织口径）证明 BO 工具
没有比页面更宽的权限口径；审计五要素贯穿四服务；写路径幂等在 Java 而非网关。

**表述建议**：内生 = 共享同一套本体、权限、审计与幂等，而非进程同体。否则会被「你这是外挂」
一句话打回——文章已备好反驳：底座优先是两条 AI 原生路径之一。

### B. 观点 4 与观点 5 之间存在方向性矛盾 —— 14 条里最深的一个

- 观点 5：Metadata 是 Ontology 的**输入和来源**（元数据→本体，下行）；
- 观点 4：Ontology 是**逻辑核心**（本体→驱动业务，上行）。

若本体永远从元数据推导而来，它是**镜子**——镜子可做校验（本仓漂移检测：增量段引用的字段/
规则必须与存量元数据一致，`FIELD_DRIFT`/`RULE_DRIFT` 必须检出），但镜子不能当核心。逻辑核心
意味着反向：表单、流程、权限、校验由本体生成或约束。

本仓现状（诚实评估）：`ap_invoice.yaml` 三段式中，投影段是下行映射，增量段是上行资产但**只做
漂移校验、不驱动结构**；原生段是规格直通（`bo-ap.yaml` 规格即工具——这是 14 条之外最超前的
一处：规格驱动的工具清单）。

**表述建议**（分阶段）：
1. 阶段一（本仓已达成）：本体 = 统一语义与校验核心（术语/指标/规则/护栏/能力问题唯一真相源 + 漂移防护）；
2. 阶段二（未达成）：本体开始驱动结构（哪怕只从增量段生成一个派生字段 API 或一条校验规则骨架）；
3. 阶段三（愿景）：本体 = 逻辑核心（结构生成的源头）。

把阶段一包装成「逻辑核心」会让懂行的人觉得言过其实。

### C. 观点 12（终局替换）vs 观点 2（存量=确定性执行）—— 终局张力 + 本仓的架构对冲

替换掉「传统执行」后，谁做确定性执行？本仓埋了答案：**治理面是执行端无关的**。T3 一次性
写令牌、审批三要素+快照+params_hash、幂等键、审计五要素——全部在网关/合同层（`bo-ap.yaml`），
不在 Java 里。未来执行端从 Java 事务换成 agent-native 服务，只要履行同一 BO 合同（同样幂等
语义、同样错误码、同样审计留痕），**管控面一行不改**。这就是「替换」能安全发生的架构前提；
本仓验证不了终局（也不该），但验证了终局发生时治理不变的前提。

## 三、未体现 / 未验证清单（P0 已补，余项按补齐性价比排序）

**已补齐（2026-09-18，见第五节）**：
1. ~~Partner（行业）层~~ —— 解析顺序槽位已填充并演示；
2. ~~Scheduler 触发~~ —— 形态⑤落地；
3. ~~多领域 Agent + 协同~~ —— 采购域切片 + 跨域委派（AP 委派采购域）落地，
   含协作清单治理与 act 委托链贯穿（scene_8）。

**余项**：
1. **Message 扩展通道**（观点 14 后半）：outbox 是内部事件；租户级「通过 Message 扩展」
   （订阅 webhook / 消息总线挂自定义处理器）没有。
2. **多异构系统对接**（文章选型第四条）：MCP 代理只指向一套 Java。哪怕再挂一个只读 OA/CRM
   工具，即可演示「底座不绑定单一 ERP」。
3. **元数据→本体自动喂养**（观点 5 的自动化方向）：投影段是手工映射；无 schema introspection
   自动生成。现状 = 人工对齐 + 机器校验，不是自动生成。
4. **产品化配置界面**（观点 13）：租户/行业配置是 YAML 文件级操作，无管理端 UI。
5. **Ontology 驱动结构**（观点 4 阶段二）：增量段不生成任何结构。
6. **更多领域与协同深度**（观点 6 的延伸）：当前为 AP × 采购两域一场景；多域编排
   （三方以上、并行委派、agent 间协商）未涉及——当前阶段以「定义好的流程为主」
   （观点 8），协同走显式委派链而非自由协商，是刻意约束。

## 四、本仓有、而 14 条没有的（建议升格为观点 15/16）

1. **可验证性是一等公民**：50 锚点评测六类（含 AP-HALLU 幻觉 / AP-MISLEAD 诱导两个负向类）；
   30 条能力问题清单与评测用例**同源绑定**（`verified_by`，两处同一份防脱节）；mock/replay/live
   三态 + `X-Model-Mode` 按请求钉定（对非确定性系统做确定性回归，定时例程钉 mock 是第三个
   应用场景）。**连护栏本身都被评测**——这是文章五条选型标准没到的高度。
2. **口径互证（对账）作为治理基础设施**：三口径权限对照、成本台账 vs 审计五要素对账、四问自检
   （谁在用/发生了什么/有无异常/花多少钱）——观点 11 说人是「监督者」，这三样是监督者的
   数据基础设施，且全部自动化可复跑。

## 五、P0/P1 补齐记录（2026-09-18）

### Partner 行业包（观点 13 的行业维度）

| 位置 | 内容 |
|---|---|
| `harness-assets/partner/guardrails/mfg-compliance.yaml` | 制造业行业护栏包：`mfg-no-gr-bypass`（无收货不得过账），`applies_to.industries: [manufacturing]` |
| `harness-assets/tenant-{east,uni}/tenant.yaml` | 租户行业声明（T-EAST=manufacturing，T-UNI=trade；非资产文件不参与叠加） |
| `erp-ai-hub/hub/assets/resolver.py` | Partner 层行业适配：`applies_to.industries` 与租户行业声明匹配才加载（不匹配记 `partner_not_applicable`）；未声明 applies_to 的 Partner 资产全局生效 |
| `erp-ai-context/overlays/partner-manufacturing.yaml` | 行业语义包：行业术语（来料发票/委外加工发票）+ 行业默认参数（大额阈值 30 万，租户可覆盖） |
| `erp-ai-context/service/loader.py` `tools.py` | 语义层 Partner 链：术语解析顺序 租户→行业包→Standard；指标口径 租户→行业包→Standard，来源取证带 partnerId/partnerVersion |

**验证**：`python scripts/demo/scene_7.py` —— T-EAST「来料发票」经 partner 层解析为 invoice、
T-UNI 同术语不命中（不跨行业串扰）；「跳过收货」话术 T-EAST 被行业护栏拦截（`HUB.GUARDRAIL_BLOCKED`，
ruleSource=partner）、T-UNI 不误伤；解析留痕同时含 standard + partner + tenant 三层护栏。

### Scheduler 定时触发（观点 10 的第三条腿）

| 位置 | 内容 |
|---|---|
| `erp-ai-hub/hub/scheduler.py` | 定时线程（形态⑤）：周期代表 ap-batch 执行全量阻断筛查；钉定 `X-Model-Mode: mock`（确定性例程，与评测同策略，零 live 配额消耗）；结果**有变化才通知**（首次必通知） |
| `hub/api.py` `POST /internal/scheduler/run` | 手动触发同一执行路径（演示/验证入口，X-Internal-Secret） |
| `workbuddy/src/pages/Notifications.tsx` | 通知 kind `SCHEDULED_BATCH`（定时筛查）标签 |
| `compose`（`SCHEDULER_ENABLED`/`SCHEDULER_INTERVAL`） | 默认启用、180 秒一跑，可调可关 |

**验证**：scene_7 —— 定时筛查返回阻断摘要；lisi 收到 SCHEDULED_BATCH 通知；审计含
trace `sched-*` 且以 ap-batch 代理身份（T2）留痕。

### 多领域 Agent 协同（观点 6，P1）

**场景（业务驱动）**：INV-A-001 被阻断，AP 侧只能回答「发票 120 vs 收货 100」的数量差异；
短交还是超开要结合采购域订单量定位（PO-A-0001 订单 100 = 已收 100 → 供应商超开 20 件）。
跨域诊断场景（xdom.diag）：ap-copilot 先 AP 归因，再**委派** proc-copilot 取证，
综合出根因与处置建议。协同的治理全部在平台层：

| 位置 | 内容 |
|---|---|
| `boapi-spec/bo-ap.yaml`（1.1.0） | 采购域最小切片两个只读操作：`proc.po.getDetail`（订单详情+按行已收汇总）、`proc.gr.listForPo`（收货取证）；复用存量权限码 ap.po.read / ap.gr.read |
| `legacy-erp-ap/.../ProcurementQueryService.java` | 采购域查询服务：租户 fail-closed + PermissionService 组织覆盖（越界按未找到，不泄露存在性） |
| `erp-ai-action/app/db.py` `registry/` | agents 表新增 `delegates_to` 协作清单（声明式种子拥有）；ap-copilot 声明 `["proc-copilot"]`；新代理 proc-copilot（T-EAST） |
| `erp-ai-action/app/auth/routes.py` | exchange 第七道校验：委派方在册/在期/同租户 + 目标在协作清单内，否则 403 `GW.DELEGATION_NOT_ALLOWED` |
| `erp-ai-action/app/auth/token_service.py` | `mint_t2` 支持 act_chain：委派时链增长为 `[proc-copilot → ap-copilot → erp-ai-hub]`（RFC 8693 嵌套），经 T3 自动贯穿至存量域审计 |
| `erp-ai-hub/hub/graphs/proc.py` `xdom.py` | 采购域场景图（独立可用 + 可被委派）与跨域诊断图（classify → AP 归因 → 委派 → 综合根因：超开/短交定位 + 处置建议） |

**验证**：scene_8 —— 综合结论含三段（AP 归因/采购取证/根因定位）；委派 T2 解码
act 嵌套链与最小权限 scope；负向三连（清单外/反向/跨租）全部 403；审计行携带
delegation_chain；采购域独立可用；跨域场景护栏前置。

## 六、一句话总结

> 14 条判断与本仓的关系：**11 条已实现且已验证（1/2/3/6/7/8/9/10/11/12/13），
> 1 条实现一半（14 的 API 半边，Message 未落地），1 条是方向性愿景需分阶段表述（4）**。
> 冲突不在代码里，在表述里：把「底座式内生」说清（A）、把「本体核心」分阶段（B）、
> 把「替换的对冲」显式化（C）——这 14 条即构成一个自洽、且大部分已被本仓
> 证实而非证伪的架构纲领。
