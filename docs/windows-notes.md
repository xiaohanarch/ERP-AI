# Windows 环境注意事项

本仓在 Windows 11 + Docker Desktop（WSL2 后端）上开发验证。以下坑均已踩过，记录于此。

## 1. 控制台编码（UTF-8）

Windows 控制台默认 GBK/cp936，脚本输出的中文与 ✓/✗ 符号会触发 `UnicodeEncodeError`。
统一解法（二选一，脚本内部已尽量自愈）：

```bash
# 方式 A：每次加 -X utf8（推荐，README 示例均带）
python -X utf8 eval/runner/run_eval.py --tier full

# 方式 B：会话级环境变量（gen_report.py 的子进程已自动注入）
export PYTHONIOENCODING=utf-8
```

heredoc/临时脚本不要写到 `/tmp`（bash 会映射到不存在 `D:\tmp` 的路径）；直接用真实仓库路径。

## 2. 用哪个 Python 跑 scripts/ 与 eval

| 脚本 | 依赖 | 建议 |
|---|---|---|
| scripts/*（tenant_checks / selfcheck / gen_report / demo/scene_* / headless_mcp） | httpx | `.venv-hub/Scripts/python.exe`（已装 httpx+yaml）或系统 Python 装 httpx |
| eval/runner/run_eval.py | httpx + PyYAML | 同上 |
| scripts/e2e_workbuddy.py | playwright | **系统 Python**（`.venv-hub` 没装 playwright；首次需 `playwright install chromium`） |

脚本端点可用环境变量覆盖（默认与 compose 一致，指向 127.0.0.1）：
`ERP_DEMO_GW / ERP_DEMO_HUB / ERP_DEMO_JAVA / ERP_DEMO_SEM / ERP_DEMO_INTERNAL_SECRET / ERP_DEMO_HUB_CLIENT_SECRET / ERP_DEMO_PASSWORD`（见 `scripts/_common.py`）。

## 3. localhost vs 127.0.0.1

- 脚本默认打 `127.0.0.1`（避免 localhost 先解析 IPv6 ::1 的等待）；
- **WorkBuddy 必须用 http://localhost:8088 打开**：OAuth 授权码流程的 `redirect_uri`
  取页面 origin，网关侧登记的是 `http://localhost:8088/callback`；用 127.0.0.1:8088 打开
  会导致 redirect_uri 不匹配被拒；
- Jaeger 用 http://localhost:16687，ERP 页面 http://localhost:8080（Thymeleaf 登录页）。

## 4. 换行与编码约定

- `.gitattributes` 强制 `* text=auto eol=lf`（`.bat` 例外 CRLF，图片/jar 二进制）——
  Windows 上请勿用编辑器把仓库文件改回 CRLF；
- 所有 YAML/Markdown/Python 均为 UTF-8 **无 BOM**；Java 源文件 UTF-8；
  compose 内 init SQL 显式 UTF-8，避免容器内 Flyway 乱码；
- 评测/种子相关 YAML 含中文，跨工具读写时注意别让 PowerShell 的 `>` 重编码（统一在 bash 里操作）。

## 5. 管道掩盖退出码

bash for Windows 里 `python xxx.py | tee log` 之后 `$?` 是 tee 的退出码。检验脚本以退出码
作为 CI 判据（0=过/1=失败/2=服务不可达），需要管道时用：

```bash
python -X utf8 scripts/tenant_checks.py | tee /tmp/t.log; echo "exit=${PIPESTATUS[0]}"
```

或在 CI 里不用管道，直接看脚本自身的汇总行。

## 6. Docker / compose

- 统一在 `compose/` 目录执行：`docker-compose up -d --build`（项目名 `erp-ai-demo`，
  `docker-compose ps` 可看全量服务）；
- 卷挂载：postgres 数据卷 + Java 构建均在容器内完成，Windows 侧无需 JDK/Maven；
  WorkBuddy 构建参数（VITE_GW_BASE / VITE_HUB_BASE）在 compose 里以 localhost 写死，
  修改后需 `docker-compose up -d --build workbuddy` 重新构建镜像（VITE 变量是构建期注入）；
- 首次启动 Java 容器要跑 Flyway 迁移 + 种子，健康检查通过前网关会显示部分服务不可达
  （检验脚本退出码 2 就是这个含义：等 30-60 秒再跑）；
- 端口占用：15432（PostgreSQL）/16687（Jaeger）/14318（OTLP）/8000-8002/8080/8088/18090，
  与本机已有服务冲突时改 compose 的端口映射即可。

## 7. 数据复位

种子数据「只增不改」。演示副作用会累积（如 INV-A-052 已应用过税码、残留 PENDING 审批单），
不影响断言（写路径幂等设计会重放首次结果），如需彻底复位：

```bash
cd compose && docker-compose down -v   # -v 连数据卷一起删
docker-compose up -d --build           # Flyway 重建 schema + 种子
```

注意：`down -v` 会清掉评测录制以外的所有运行时状态（审批单/审计/成本台账/挂起检查点），
`compose/recordings/` 在宿主机卷上，不受影响。
