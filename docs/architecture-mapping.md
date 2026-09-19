# 总纲 14 章 ↔ 代码映射表

> 真源：[`erp-ai-architecture-master.html`](../erp-ai-architecture-master.html)（保留在根目录，未改动）
> 本文回答：「总纲这一章，在本仓落在哪、怎么验证」。所有验证入口都在运行中的服务上执行（启动见 [README](../README.md)）。

## 一览

| # | 总纲章节 | 本仓落点 | 验证入口 |
|---|---|---|---|
| 01 | 业界现在在做什么 | （背景章，无代码）演示复现其指出的两类事故：数据权限口径差、「页面能看的 AI 也能看」的对齐 | `python scripts/demo/scene_1.py` |
| 02 | ERP AI 技术架构 L0：七层结构与两条贯穿线 | L0 接入域 `legacy-erp-ap/.../web/`（ERP 页内嵌 copilot）+ `workbuddy/`（助手平台）+ `scripts/headless_mcp.py`（无头）+ `erp-ai-hub/hub/events.py`（事件触发）+ `erp-ai-hub/hub/scheduler.py`（定时触发）+ `erp-ai-hub/hub/graphs/xdom.py`（跨域协同：AP 委派采购域）；L1 网关 `erp-ai-action/`；L2 Hub `erp-ai-hub/`；L3 语义 `erp-ai-context/`；L4 存量 `legacy-erp-ap/`；模型网关 `erp-ai-action/app/modelgw/`。两条贯穿线：身份（T1→T2→T3，见 [token-design.md](token-design.md)）与评测（`eval/`） | `python scripts/selfcheck.py`（四问）；`python scripts/demo/scene_8.py` |
| 03 | appid 策略与部署架构 | appid 清单：`erp-ap`（存量，Java）、`erp-ai-action`（网关）、`erp-ai-hub`（业务 Hub）、`erp-ai-context`（语义）；服务边界即 `compose/docker-compose.yml` 的服务列表 | `docker-compose ps`；网关 `/healthz` |
| 04 | 租户体系下的 harness | 标品资产层 `harness-assets/standard/{skills,rules,guardrails,prompts,evalsets}` + 行业包层 `partner/`（制造业示例：行业护栏按租户行业声明匹配加载）+ 租户层 `tenant-east/`、`tenant-uni/`；三层解析器 `erp-ai-hub/hub/assets/resolver.py`（Standard→Partner→Tenant，仅 `overridable` 可覆盖，护栏只加严）；租户语义叠加 `erp-ai-context/overlays/`（含行业语义包）+ **配置存储 DB 层**（`service/config_store.py`：管理端改完即生效，文件层为出厂默认）；租户消息订阅（Message 扩展通道）`erp-ai-action/app/subscriptions/` | `python scripts/tenant_checks.py`（六项）；`python scripts/demo/scene_7.py` `scene_9.py` `scene_10.py`；WorkBuddy「解析查看器」/「租户配置」页 |
| 05 | AI 应用的鉴权与授权 | Agent 注册中心 `erp-ai-action/app/registry/`（清册/吊销/SoD 互斥/协作清单 delegates_to）；逐跳令牌 `app/auth/`（T1/IN/T2/T3/OT + OAuth 授权码）；拦截链 `app/auth/routes.py` 的 `/gw/auth/exchange`（七道：注册/吊销/租户/场景/scope/SoD/**委派授权**——Agent 间委派须在协作清单内，act 链增长）；审批 `app/approval/`；Java 侧判定 `legacy-erp-ap/.../security/` | `python scripts/demo/scene_3.py` `scene_4.py` `scene_6.py` `scene_8.py`；[token-design.md](token-design.md) |
| 06 | BO API：共识、规格、证据与落地 | ★ 全项目唯一规格真源 `boapi-spec/bo-ap.yaml`（OpenAPI 3.1 + `x-bo-extensions`：操作性质/不可逆/幂等键/错误分类/completeness/正反例）；BO 实现 `legacy-erp-ap/.../boapi/`；MCP 工具定义由规格生成 `.../mcp/`；适配层补齐 completeness（权限不足时披露而非静默） | `python scripts/demo/scene_2.py`；`PermissionParityTest`（Java 测试） |
| 07 | 知识库怎么建 | 语义文件三段式（投影/增量/原生）`erp-ai-context/domains/ap_invoice.yaml`；**投影段由存量元数据自动喂养**（`service/loader.effective_projection`：实体清单/标签/枚举实时生成，人工只维护口径层）；**增量段驱动结构**（`scripts/gen_derived_fields.py` 构建期生成派生字段定义 → Java 通用求值 `DerivedFieldService` → BO 操作 `ap.invoice.getDerivedField`）；七个语义查询工具；能力问题清单 `questions-capability.yaml`（30 条）；漂移检测 `drift/drift_check.py`（预埋 2 处漂移可检出 + 术语目标/派生基字段两条新不变式） | `python erp-ai-context/drift/drift_check.py`；`python scripts/demo/scene_5.py` `scene_11.py` |
| 08 | Agent 评测集怎么建 | 50 条锚点用例 `eval/cases/ap-{perm,diag,tool,mislead,hallu,comp}.yaml`（六类：15/8/10/7/6/4，含 AP-PERM-003 与越权诱导 AP-MISLEAD-001）；确定性检查层 `eval/runner/run_eval.py`（工具名/禁调/步数/不变式，replay 默认）；分层 smoke/regression/full | `python -X utf8 eval/runner/run_eval.py --tier full`（50/50，门禁全绿） |
| 09 | Agent 成熟度分级 | 以可检验指标落位：工具正确性 ≥98% / 参数 ≥95% / 步数 ≤4 / 不完整披露 100%（零容忍）/ 越权 0（阻断）——写入 `docs/verification-report.md` 的指标节 | `python scripts/gen_report.py` |
| 10 | 框架、Harness 与开发语言的选型 | LangGraph 收敛在薄封装 `erp-ai-hub/hub/sdk/graph.py`（唯一允许 import langgraph 的层）；interrupt 审批断点 `hub/graphs/taxcode.py` + PostgresSaver；Spring AI MCP Server 在 Java 侧；网关/Hub 用 FastAPI；前端 React+Vite | `python scripts/demo/scene_6.py`（挂起→唤醒） |
| 11 | 可审计的 AI：ERP 产品要交付什么 | 审计五要素入库 `erp-ai-action/app/audit/`（时间/租户/用户/Agent/动作+结果+错误码+审批单号）；Agent 清册 `/gw/agents`；审批留痕（approver+snapshot）`app/approval/`；证据包导出 `/gw/evidence/export`（委托链+审批快照+审计摘录+版本四件套）；五分钟自检 `scripts/selfcheck.py` | scene_6；`python scripts/selfcheck.py`；报告 `docs/selfcheck-latest.md` |
| 12 | AI Agent 体系的可观测 | OTel GenAI 风格 span 树 `erp-ai-action/app/otel_setup.py`（invoke_agent→chat→execute_tool，六组扩展字段：身份/版本/场景/完整性/动作性质/内容摘要）；成本台账 `app/cost/`（tenant/agent/scene/user 四维 token 计量，与审计对账）；Jaeger compose 内置 | http://localhost:16687（Jaeger）；自检 Q4 成本对账 |
| 13 | 工程之外还有五个问题 | （组织/合规/数据治理等，非代码章）演示叙事落位：十一幕剧本每幕的「讲解词」 | [demo-script.md](demo-script.md) |
| 14 | 总路线图与子产品 Playbook | WAVE 0→1→2 实施顺序即本仓 Phase 0-3：身份留痕先于场景（Phase 0）、评测先于知识、读侧先于写侧（Phase 1→2） | 本仓 git 历史（tag v0.x）+ `docs/verification-report.md` |

## 关键「规格即真源」派生关系

`boapi-spec/bo-ap.yaml` 是冻结件，以下全部**派生**自它，不允许旁路手写：

```
bo-ap.yaml ──构建期 codegen──▶ legacy-erp-ap MCP 工具定义（规格即工具）
           ──加载──▶ erp-ai-action/app/mcp/tool_registry.py（网关工具注册表）
           ──引用──▶ eval/cases/*.yaml（期望值锚定规格示例）
           ──投影段──▶ erp-ai-context/domains/ap_invoice.yaml（operations 引用）
```

改规格 → 版本戳变更 → 录制自动作废 → 评测重跑（三版本戳：spec/seed/semantics，任一变更录制失效）。

## 版本四件套（评测证据锚点）

`GET /gw/versions`：`specVersion 1.0.0` / `rulesetVersion AP-RS-1.2.0` / `seedVersion ap-seed-1.0.0` /
`semanticsVersion ap-sem-1.0.0`（+ 模型模式：mock/replay/live）。证据包与检验报告均携带，
保证「跑的是什么版本」可回答。

## 双租户与四种 Agent 形态

- 租户：`T-EAST 华东制造` / `T-UNI 星联科技`（用户：张三/李四/王五 · 赵六/钱七/孙八，口令 `demo123`）
- 形态① ERP 页面内嵌 copilot + AI Command：`legacy-erp-ap/.../web/`（Thymeleaf + SSE）
- 形态② WorkBuddy 助手平台（OAuth 授权码）：`workbuddy/`（React，端口 8088）
- 形态③ 无头 MCP 脚本：`scripts/headless_mcp.py`
- 形态④ 事件触发：`legacy-erp-ap/.../event/`（outbox `ap.invoice.blocked`）→ `erp-ai-hub/hub/events.py`（无头诊断 → 通知）
