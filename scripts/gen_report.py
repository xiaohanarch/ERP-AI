#!/usr/bin/env python3
"""检验报告生成器：汇总 全量评测 / 多租六项 / 漂移检测 / 五分钟自检 / 事故三口径 / 版本戳。

依次以子进程运行四个检验体系（各自独立退出码），再聚合三口径取证与版本四件套，
产出 docs/verification-report.md（生成物，不入库）。

用法: python scripts/gen_report.py
退出码: 0 = 全部体系绿；1 = 任一体系存在失败；2 = 服务不可达。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import _common as C

OUT = Path(C.REPO) / "docs" / "verification-report.md"
EVAL_FULL_JSON = Path(C.REPO) / "eval" / "reports" / "full-latest.json"
TENANT_JSON = Path(C.REPO) / "eval" / "reports" / "tenant-checks-latest.json"
DRIFT_SCRIPT = Path(C.REPO) / "erp-ai-context" / "drift" / "drift_check.py"

# 漂移检测的预期口径：预埋漂移必须全部检出（检出 = 通过，未检出 = 失败）
EXPECTED_DRIFTS = {"FIELD_DRIFT", "RULE_DRIFT"}


def _run(label: str, script: Path, *args: str) -> tuple[int, str]:
    """子进程运行检验脚本（UTF-8 环境），返回 (退出码, 输出尾部)。"""
    cmd = [sys.executable, "-X", "utf8", str(script), *args]
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(C.REPO), env=env, timeout=900)
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-4:])
    print(f"  [{ 'OK' if proc.returncode in (0, 1) else 'ERR' }] {label} 退出码 {proc.returncode}"
          + (f"（{tail.splitlines()[-1]}）" if tail else ""))
    return proc.returncode, proc.stdout or ""


def run_eval() -> dict:
    print("── 体系 1/4：全量评测（50 锚点用例，replay/确定性层）")
    code, _ = _run("eval full", Path(C.REPO) / "eval" / "runner" / "run_eval.py", "--tier", "full")
    if not EVAL_FULL_JSON.exists():
        return {"ok": False, "error": f"评测报告缺失（退出码 {code}）"}
    data = json.loads(EVAL_FULL_JSON.read_text(encoding="utf-8"))
    data["_exit"] = code
    return data


def run_tenant() -> dict:
    print("── 体系 2/4：多租六项检验")
    code, _ = _run("tenant_checks", Path(C.REPO) / "scripts" / "tenant_checks.py")
    if not TENANT_JSON.exists():
        return {"ok": False, "error": f"租检报告缺失（退出码 {code}）"}
    data = json.loads(TENANT_JSON.read_text(encoding="utf-8"))
    data["_exit"] = code
    return data


def run_drift() -> dict:
    print("── 体系 3/4：漂移检测（语义增量段 vs 存量元数据）")
    code, out = _run("drift_check", DRIFT_SCRIPT, "--json", "--base", C.JAVA)
    try:
        start = out.index("{")
        data = json.loads(out[start:])
    except (ValueError, json.JSONDecodeError):
        return {"ok": False, "error": f"漂移报告解析失败（退出码 {code}）"}
    data["_exit"] = code
    # 预期口径：预埋漂移全部检出（漂移检出 -> 检验通过，退出码 1 是预期）
    kinds = {d["kind"] for d in data.get("items", [])}
    data["_expectedMet"] = EXPECTED_DRIFTS.issubset(kinds) and data.get("drifted") is True
    return data


def run_selfcheck() -> dict:
    print("── 体系 4/4：五分钟自检（四问）")
    code, _ = _run("selfcheck", Path(C.REPO) / "scripts" / "selfcheck.py")
    return {"_exit": code, "ok": code == 0}


def caliber_section() -> tuple[str, bool]:
    """事故三口径取证（张三 T-EAST：页面 vs Open API vs BO API）。"""
    c = C.three_calibers("zhangsan", "T-EAST")
    bo = c["bo"]
    checks = C.caliber_checks(c)
    ok = all(x[1] for x in checks)
    dims = (bo.get("filteredByDimension") or {}).get("dimensions") or []
    lines = [
        "| 口径 | 行数 | 权限语义 |",
        "|---|---|---|",
        f"| ERP 页面（会话 + 组织过滤） | {c['uiTotal']} | 张三仅见 ORG-EAST-PROC |",
        f"| Open API（appid 直连，租户级） | {c['openapiTotal']} | **事故口径**：无组织过滤，全租可见 |",
        f"| BO API（T3，与页面同权限组件） | {bo['total']}（阻断子集） | 同组织口径 + filteredByDimension 披露 |",
        "",
        f"- BO API 披露维度：{dims}；命中组织：{bo['orgs']}；命中单据：{', '.join(bo['items'][:8])}"
        + ("…" if len(bo["items"]) > 8 else ""),
        "- 断言：" + "；".join(f"{n} {'✓' if o else '✗'}" for n, o, _ in checks),
    ]
    return "\n".join(lines), ok


def main() -> int:
    print("=== 检验报告生成（gen_report）===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[gen_report] 服务不可达：{down} —— 请先启动 compose")
        return 2

    versions = C.collect_versions()
    ev = run_eval()
    tc = run_tenant()
    dr = run_drift()
    sc = run_selfcheck()
    print("── 附加取证：事故三口径对照")
    try:
        caliber_md, caliber_ok = caliber_section()
    except Exception as e:  # noqa: BLE001
        caliber_md, caliber_ok = f"取证失败：{e}", False

    # ---- 判定 ----
    ev_ok = bool(ev.get("all_ok"))
    tc_ok = bool(tc.get("ok"))
    dr_ok = bool(dr.get("_expectedMet"))
    sc_ok = bool(sc.get("ok"))
    all_green = ev_ok and tc_ok and dr_ok and sc_ok and caliber_ok

    model_name = versions.get("model") or {"mock": "mock-scene-model", "replay": "replay 录制"}.get(
        str(versions.get("modelMode")), versions.get("model") or str(versions.get("modelMode")))
    m = ev.get("metrics") or {}
    by_cat = ev.get("by_category") or {}

    md = ["# 验证报告（verification report）", "",
          f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
          f"- 版本戳：spec `{versions.get('specVersion')}` / ruleset `{versions.get('rulesetVersion')}`"
          f" / seed `{versions.get('seedVersion')}` / 语义 `{versions.get('semanticsVersion')}`"
          f" / 模型 `{model_name}`（{versions.get('modelMode')}）",
          f"- 结论：**{'全部体系绿' if all_green else '存在失败项（见下表）'}**",
          "",
          "## 一、总览", "",
          "| 检验体系 | 结果 | 判定 |",
          "|---|---|---|",
          f"| 全量评测（50 锚点用例） | {ev.get('passed', 0)}/{ev.get('total', 0)} 通过，"
          f"耗时 {ev.get('elapsed_seconds', 0)}s | {'✅' if ev_ok else '❌'} |",
          f"| 多租六项检验 | {tc.get('passed', 0)}/{tc.get('total', 0)} 通过 | {'✅' if tc_ok else '❌'} |",
          f"| 漂移检测 | 检出 {(dr.get('counts') or {}).get('drifts', 0)} 处预埋漂移"
          f"（{'全部检出' if dr_ok else '未全部检出'}） | {'✅' if dr_ok else '❌'} |",
          f"| 五分钟自检（四问） | {'全部可答' if sc_ok else '存在告警'}（docs/selfcheck-latest.md）"
          f" | {'✅' if sc_ok else '❌'} |",
          f"| 事故三口径断言 | 页面 ~50 / Open API ≥5050（~100 倍）/ BO 同权限口径 | {'✅' if caliber_ok else '❌'} |",
          ""]

    md += ["## 二、评测指标 vs 目标", "",
           "| 指标 | 实测 | 目标 | 判定 |", "|---|---|---|---|"]
    gates = ev.get("gates") or {}
    rows = [
        ("工具正确性", m.get("tool_correctness"), "≥ 0.98", gates.get("tool_rate_target")),
        ("参数正确性", m.get("param_correctness"), "≥ 0.95", gates.get("param_rate_target")),
        ("最大步数", m.get("max_steps_seen"), "≤ 4", gates.get("steps_target")),
        ("禁调违规", m.get("forbidden_tool_violations"), "= 0", gates.get("forbidden_zero")),
        ("零容忍失败（AP-COMP/AP-HALLU）", m.get("zero_tolerance_failures") or "无", "= 0",
         gates.get("zero_tolerance_pass")),
    ]
    for name, val, target, ok in rows:
        md.append(f"| {name} | {val} | {target} | {'✅' if ok else '❌'} |")
    md.append("")

    md += ["## 三、评测用例六类分布", "", "| 类别 | 通过/总数 |", "|---|---|"]
    for cat in sorted(by_cat):
        c = by_cat[cat]
        md.append(f"| {cat} | {c['passed']}/{c['total']} |")
    md.append("")

    md += ["## 四、多租六项明细", ""]
    items = tc.get("items") or []
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(it.get("group") or "其他", []).append(it)
    order = ["A0 叠加", "术语叠加", "派生指标", "三层解析", "跨租隔离", "成本归集", "其他"]
    for g in order:
        if g not in groups:
            continue
        sub = groups[g]
        bad = [i for i in sub if not i["ok"]]
        md.append(f"- **{g}**：{len(sub) - len(bad)}/{len(sub)} 通过"
                  + ("" if not bad else f" —— 失败：{'；'.join(i['name'] for i in bad)}"))
    md.append("")

    md += ["## 五、漂移检测明细（预埋漂移必须检出）", ""]
    for d in dr.get("items") or []:
        md.append(f"- [{d['kind']}/{d['severity']}] {d['detail']}")
    base = dr.get("baseline") or {}
    md += ["", f"- 基线：ruleset `{base.get('ruleSetVersion')}` / seed `{base.get('seedVersion')}`"
           f" / 语义 `{base.get('semanticVersion')}`；检查字段 {(dr.get('counts') or {}).get('checkedFields', 0)}"
           f" 个、规则 {(dr.get('counts') or {}).get('checkedRules', 0)} 条", ""]

    md += ["## 六、事故三口径对照（张三，T-EAST）", "", caliber_md, "",
           "---",
           "生成物：`docs/verification-report.md`（本文件）、`docs/selfcheck-latest.md`、"
           "`eval/reports/full-latest.{json,md}`、`eval/reports/tenant-checks-latest.json`。", ""]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8", newline="\n")
    print(f"\n[gen_report] 结论：{'全部体系绿' if all_green else '存在失败项'}")
    print(f"[gen_report] 报告 -> {OUT}")
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())