# ERP-Demo：Agentic-ERP AI 参考架构（可运行演示）

把《ERP AI 技术架构总纲》（14 章，`erp-ai-architecture-master.html`）的核心机制做成**真实可运行、
可检验**的工程参考：跑通「用户 → 网关 → Agent → BO API → Java 存量应付模块」全链路，
复现「页面 50 条 vs Open API 5000 条」权限事故，通过 50 条评测用例，输出双租户六项检验报告。

**不是 PPT**——每个主张都有对应的代码落点和可重复执行的断言（总纲 14 章 ↔ 代码映射见
[docs/architecture-mapping.md](docs/architecture-mapping.md)）。

## 一键启动

```bash
cd compose
docker-compose up -d --build     # 首次含 Java 构建 + Flyway 迁移 + 种子，约 2-4 分钟
docker-compose ps                # 全部 healthy 后（约 30-60 秒）即可验证
```

无需模型 API key 即可跑通全部验证：开箱默认 `MODEL_MODE=mock`（脚本化确定性应答）。
想接真实模型，复制 `compose/.env.example` 为 `compose/.env`，改 `MODEL_MODE=live` + `LIVE_*`：
协议二选一——`LIVE_PROTOCOL=openai`（DeepSeek/GLM/Qwen 的 OpenAI 兼容端点）或
`LIVE_PROTOCOL=anthropic`（Anthropic Messages 兼容端点，如 GLM 经 Anthropic 兼容网关接入）。
切 live 后评测/演示脚本仍保持确定性：它们按请求钉定 `X-Model-Mode: mock`，只有交互面
（WorkBuddy / ERP 页面 copilot）走真实模型。

## 服务与端口

| 服务 | appid | 地址 | 说明 |
|---|---|---|---|
| AI 网关 | `erp-ai-action` | http://localhost:8000 | Agent 注册中心 · 令牌交换 · MCP 代理 · 审批 · 模型网关 · 审计 |
| 业务 Hub | `erp-ai-hub` | http://localhost:8001 | LangGraph 场景图（诊断/批量/税码+interrupt 审批断点） |
| 语义服务 | `erp-ai-context` | http://localhost:8002 | 语义文件 + 七个语义查询工具 + 租户叠加 |
| 存量 ERP（AP） | `erp-ap` | http://localhost:8080 | Java Spring Boot：UI API + BO API + Open API 事故端点 + Spring AI MCP + Thymeleaf 页面 |
| WorkBuddy | — | http://localhost:8088 | React 助手平台（OAuth 授权码 / 聊天 / 审批 / 通知 / 解析查看器） |
| Jaeger | — | http://localhost:16687 | OTel GenAI 风格 span 树 |
| PostgreSQL | — | localhost:15432 | 审计/审批/幂等/成本/检查点 |
| mock-model | — | localhost:18090 | OpenAI 兼容脚本化应答 |

## 演示账号（口令一律 `demo123`）

| 用户 | 租户 | 角色 | 用途 |
|---|---|---|---|
| zhangsan 张三 | T-EAST 华东制造 | 采购经理 | 无预算权限 → 事故与 completeness 主角 |
| lisi 李四 | T-EAST | 财务 | 全权限，写路径发起人 |
| wangwu 王五 | T-EAST | 经理 | 审批人 |
| zhaoliu / qianqi / sunba | T-UNI 星联科技 | 对应角色 | 双租户对照 |

Open API 事故端点凭据：`open-erp-east / open-east-secret`、`open-erp-uni / open-uni-secret`。

## 五分钟验证（全部独立退出码，CI 可用）

```bash
# 1) 四问自检（谁在用/批了什么/依据/什么版本）
python -X utf8 scripts/selfcheck.py

# 2) 多租户六项检验（A0 叠加/术语/派生指标/三层解析/跨租隔离/成本归集）
python -X utf8 scripts/tenant_checks.py

# 3) 全量评测（50 锚点用例，replay 确定性层，六类：perm/diag/tool/mislead/hallu/comp）
python -X utf8 eval/runner/run_eval.py --tier full

# 4) 语义漂移检测（预埋 2 处漂移必须检出）
python -X utf8 erp-ai-context/drift/drift_check.py --base legacy-erp-ap

# 5) 汇总报告 → docs/verification-report.md
python -X utf8 scripts/gen_report.py

# 6) 九幕演示（每幕一断言集）
python scripts/demo/scene_1.py   # 事故复现：页面 ~50 / Open API 5000+ / BO API 同权限口径
python scripts/demo/scene_2.py   # completeness：张三见数量差异+披露，李四见完整结论
python scripts/demo/scene_3.py   # 越权诱导三道拦截（护栏/SoD/scope）
python scripts/demo/scene_4.py   # 未注册/吊销即时生效
python scripts/demo/scene_5.py   # 双租同题不同答（阈值/术语/余额口径）
python scripts/demo/scene_6.py   # 审批留痕 + 证据包 + 自检
python scripts/demo/scene_7.py   # 行业包（Partner 层）+ 定时触发（Scheduler）
python scripts/demo/scene_8.py   # 多领域 Agent 协同（AP 委派采购域，act 链 + 协作清单）
python scripts/demo/scene_9.py   # Message 扩展（租户消息订阅，隔离投递 + HMAC + 吊销即停）

# 7) WorkBuddy 浏览器 E2E（Playwright，19 项检查，需系统 Python + playwright install chromium）
python scripts/e2e_workbuddy.py
```

Windows 环境的编码/Python 选择/端口注意事项见 [docs/windows-notes.md](docs/windows-notes.md)。

## 浏览器里看什么

- **ERP 页面（形态①）**：http://localhost:8080/login（zhangsan）→ 发票列表 + 页内嵌
  copilot（SSE 流式）+ AI Command；
- **WorkBuddy（形态②）**：http://localhost:8088（lisi 登录）→ Chat 选场景发起 →
  写请求出现审批卡片 → 换 wangwu 在 Approvals 批准（三要素 + 快照）→ 解析查看器看
  三层护栏（standard/partner/tenant，放松类叠加被拒）→ Notifications。
  支持深链直达演示：`/chat?scene=ap.diag&q=…` 登录后自动发起对话（`docs/intro.html`
  里所有「▶」链接即此格式）；
- **Agent 清册**：http://localhost:8000/gw/agents；**版本四件套**：http://localhost:8000/gw/versions；
- **Jaeger（形态④事件链路 trace）**：http://localhost:16687；
- **无头 MCP（形态③）**：`python scripts/headless_mcp.py list`。

## 目录结构

```
boapi-spec/bo-ap.yaml     ★ 全项目唯一规格真源（OpenAPI 3.1 + x-bo-extensions），其余全派生
legacy-erp-ap/            Java 存量域（UI API/BO API/Open API/规则引擎/PermissionService/MCP）
erp-ai-action/            Python AI 网关（注册中心/令牌/审批/模型网关/审计/成本/OTel）
erp-ai-hub/               LangGraph Hub（薄封装 sdk/ + 三图 + 三层解析器 + 事件订阅 + 定时调度）
erp-ai-context/           语义服务（domains/ 三段式 + overlays/ 双租与行业包叠加 + drift/）
harness-assets/           资产层（standard/ + partner/ 行业包 + tenant-east/ + tenant-uni/）
workbuddy/                React 助手平台
eval/                     50 条锚点用例 + 三层 runner（deterministic/judge/采样）
scripts/                  检验体系（tenant_checks/selfcheck/gen_report）+ demo 九幕 + headless
compose/                  docker-compose 一键起
docs/                     映射表 / 演示剧本 / 令牌设计 / Windows 注意事项 / 验证报告（生成物）
```

## 核心机制速览

- **规格即真源**：MCP 工具定义、网关注册表、评测期望、语义投影全部派生自 `bo-ap.yaml`；
  改规格 → 版本戳变更 → 录制作废 → 评测重跑（spec/seed/semantics 三戳，`GET /gw/versions`）。
- **逐_hop 令牌收窄**（RFC 8693 风格）：T1[chat] → T2[场景∩Agent 清单] → T3[单工具 60s] →
  OT[单工具+参数指纹 120s 一次性]，claims/拦截链/审批时序见 [docs/token-design.md](docs/token-design.md)。
- **权限判定只在存量域**：T3 进 Java 后走与页面同一个 `PermissionService`（三维数据权限），
  AI 链路零权限计算——「页面能看的 AI 也能看」是机制（`PermissionParityTest`）。
- **不可逆即审批**：网关见 `x-bo-irreversible` → 建 approval_task → hub interrupt 挂起
  （零常驻凭据）→ 批准铸 OT → 唤醒重发 → 两层幂等（网关短窗 + 业务唯一约束同事务）。
- **三层 harness 解析**：Standard→Partner→Tenant 确定性顺序，仅 `overridable` 可覆盖，
  护栏只加严（放松被拒），WorkBuddy「解析查看器」可视化。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/intro.html](docs/intro.html) | 项目介绍页（概况 + 架构 + 使用指南，可直接浏览器打开） |
| [docs/architecture-mapping.md](docs/architecture-mapping.md) | 总纲 14 章 ↔ 代码映射 + 验证入口 |
| [docs/architecture-alignment.md](docs/architecture-alignment.md) | 14 条 AI-Native 架构判断 × 本仓对照（一致性/张力/缺口） |
| [docs/demo-script.md](docs/demo-script.md) | 九幕演示剧本（讲解词 + 断言 + 浏览器路径） |
| [docs/token-design.md](docs/token-design.md) | 令牌链路 / claims / 拦截链 / 审批 OT / 幂等 |
| [docs/windows-notes.md](docs/windows-notes.md) | Windows 编码 / Python / Docker 注意事项 |
| [docs/verification-report.md](docs/verification-report.md) | 检验报告（`gen_report.py` 生成物） |
