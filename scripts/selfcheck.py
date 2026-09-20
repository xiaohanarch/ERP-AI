#!/usr/bin/env python3
"""五分钟自检：四问 markdown（运营面可快速回答的四个问题）。

  Q1 谁在用？        Agent 清册（注册状态 / 工具面 / 归属）
  Q2 刚才发生了什么？ 审计五要素最近事件（时间/租户/用户/Agent/动作/结果/错误码）
  Q3 有没有异常？    拦截与拒绝分布（护栏 / 越权 / 未注册 / 吊销）+ 评测最新结果
  Q4 花了多少钱？    双租成本台账 + 审计对账

用法: python scripts/selfcheck.py
退出码: 0 = 服务全可达且对账一致；1 = 异常；2 = 服务不可达。
产出: docs/selfcheck-latest.md（生成物，不入库）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import _common as C

OUT = Path(C.REPO) / "docs" / "selfcheck-latest.md"
EVAL_DIR = Path(C.REPO) / "eval" / "reports"

# 已知拒绝/错误码：护栏与策略拦截 + 评测/租检/scene 负向断言刻意触发的业务拒绝
# （跨租隔离探针、草稿/权限负向用例、scene_11 未在本体定义的派生字段），
# 以及交互面正常操作会产生的业务拒绝（对已决定/过期审批再决定 = 状态冲突，UI 列表滞后或重复点击即触发）。
# 出现这些 = 机制生效；出现清单之外的错误码才视为异常信号。
REJECT_CODES = ("HUB.GUARDRAIL_BLOCKED", "GW.SCOPE_EXCEEDED", "GW.AGENT_NOT_REGISTERED",
                "GW.AGENT_REVOKED", "GW.TENANT_MISMATCH", "GW.SOD_CONFLICT",
                "GW.DELEGATION_NOT_ALLOWED",
                "AP.PERMISSION_DENIED", "GW.APPROVAL_REQUIRED",
                "AP.INVOICE_NOT_FOUND", "AP.INVOICE_IN_DRAFT", "AP.PO_NOT_ACCESSIBLE",
                "AP.PO_NOT_FOUND", "AP.IDEMPOTENCY_CONFLICT", "GW.APPROVAL_PARAMS_MISMATCH",
                "AP.DERIVED_FIELD_NOT_FOUND", "GW.APPROVAL_STATE_CONFLICT")


def q1_agents() -> tuple[str, bool]:
    data = C.gw_get("/gw/agents")
    lines = ["| Agent | 租户 | 状态 | 工具数 | 负责人 |", "|---|---|---|---|---|"]
    for a in data["agents"]:
        status = "在册" if a.get("status") == "ACTIVE" else f"**{a.get('status')}**"
        lines.append(f"| {a['agentId']} | {a.get('tenantId')} | {status} "
                     f"| {len(a.get('tools') or [])} | {a.get('owner') or '-'} |")
    revoked = [a for a in data["agents"] if a.get("status") != "ACTIVE"]
    note = f"（共 {data['count']} 个，其中吊销/停用 {len(revoked)} 个）" if revoked \
        else f"（共 {data['count']} 个，全部在册）"
    return "\n".join(lines) + f"\n\n{note}", data["count"] > 0


def q2_recent_audit() -> tuple[str, bool]:
    data = C.gw_get("/internal/audit", {"limit": 15})
    items = data["items"]
    lines = ["| 时间 | 租户 | 用户 | Agent | 动作 | 结果 | 错误码 | 审批 |", "|---|---|---|---|---|---|---|---|"]
    for r in items:
        ts = str(r.get("ts", ""))[:19]
        lines.append(f"| {ts} | {r.get('tenant_id') or '-'} | {r.get('user_id') or '-'} "
                     f"| {r.get('agent_id') or '-'} | {r.get('action')} | {r.get('outcome')} "
                     f"| {r.get('error_code') or '-'} | {r.get('approval_id') or '-'} |")
    if not items:
        return "（无审计记录）", False
    return "\n".join(lines), True


def q3_anomalies() -> tuple[str, bool]:
    data = C.gw_get("/internal/audit", {"limit": 500})
    codes = Counter(str(r.get("error_code")) for r in data["items"]
                    if r.get("outcome") in ("DENIED", "ERROR") and r.get("error_code"))
    known = set(REJECT_CODES)
    guardrail_hits = codes.get("HUB.GUARDRAIL_BLOCKED", 0)
    unexpected = {c: n for c, n in codes.items() if c not in known}

    lines = [f"- 近 500 条审计中拒绝/错误 {sum(codes.values())} 条："]
    for code, n in sorted(codes.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - `{code}` × {n}")
    lines.append(f"- 其中护栏拦截（诱导/越权话术）{guardrail_hits} 条 —— 拦截即机制生效，非事故。")
    if unexpected:
        lines.append("- 关注非预期错误码：" + "、".join(f"`{c}`×{n}" for c, n in unexpected.items()))

    # 评测最新结果（若已运行）
    eval_note = "尚未运行（`python eval/runner/run_eval.py --tier full`）"
    latest = _latest_eval()
    if latest:
        eval_note = (f"{latest['tier']} 档 {latest['passed']}/{latest['total']} 通过"
                     + ("（全绿）" if latest.get("all_ok") else "（**存在失败**）"))
    lines.append(f"- 评测锚点：{eval_note}")

    # 未预期错误码 = 除已知护栏/策略错误码外的 DENIED/ERROR
    return "\n".join(lines), not unexpected


def _latest_eval() -> dict | None:
    """最新评测报告（full > regression > smoke；同档取最近修改）。"""
    priority = {"full": 3, "regression": 2, "smoke": 1}
    best = None
    for path in EVAL_DIR.glob("*-latest.json"):
        tier = path.name.replace("-latest.json", "")
        if tier not in priority or tier == "tenant-checks":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        key = (priority[tier], path.stat().st_mtime)
        if best is None or key > best[0]:
            best = (key, data)
    return best[1] if best else None


def q4_cost() -> tuple[str, bool]:
    summary = C.gw_get("/gw/cost/summary")
    recon = summary.get("reconciliation", {})
    lines = ["| 租户 | 调用数 | token 合计 | 审计对账 |", "|---|---|---|---|"]
    for tenant, v in sorted(summary.get("byTenant", {}).items()):
        r = recon.get(tenant, {})
        match = "一致" if r.get("match") else "**不一致**"
        lines.append(f"| {tenant} | {v.get('calls', 0)} | {v.get('totalTokens', 0):,} | {match} |")
    all_match = all(bool(r.get("match")) for r in recon.values()) if recon else False
    return "\n".join(lines), all_match


def main() -> int:
    print("=== 五分钟自检（selfcheck）===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[selfcheck] 服务不可达：{down} —— 请先启动 compose")
        return 2

    versions = C.collect_versions()
    sections, flags = [], []
    for title, fn in (("Q1 谁在用？（Agent 清册）", q1_agents),
                      ("Q2 刚才发生了什么？（审计五要素·最近 15 条）", q2_recent_audit),
                      ("Q3 有没有异常？（拦截与拒绝分布）", q3_anomalies),
                      ("Q4 花了多少钱？（双租成本与对账）", q4_cost)):
        try:
            body, ok = fn()
        except Exception as e:  # noqa: BLE001
            body, ok = f"查询失败：{e}", False
        sections.append((title, body))
        flags.append(ok)
        print(f"  [{'PASS' if ok else 'WARN'}] {title}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = ["# 五分钟自检报告", "",
          f"- 生成时间：{now}",
          f"- 服务健康：{'全部可达' if not down else '不可达 ' + str(down)}",
          f"- 版本戳：spec `{versions.get('specVersion')}` / ruleset `{versions.get('rulesetVersion')}`"
          f" / seed `{versions.get('seedVersion')}` / 语义 `{versions.get('semanticsVersion')}`"
          f" / 模型 `{versions.get('model')}`（{versions.get('modelMode')}）",
          ""]
    for title, body in sections:
        md += [f"## {title}", "", body, ""]
    verdict = "全部可答" if all(flags) else "存在告警项（见 Q3/Q4）"
    md += ["---", f"结论：四问 {verdict}。", ""]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8", newline="\n")
    print(f"\n[selfcheck] 四问 {verdict}")
    print(f"[selfcheck] 报告 -> {OUT}")
    return 0 if all(flags) else 1


if __name__ == "__main__":
    sys.exit(main())
