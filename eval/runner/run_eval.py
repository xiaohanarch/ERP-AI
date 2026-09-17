#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三层评测 runner · 第一层：确定性检查（工具/参数/步数/禁调/错误码/披露）。

用法（在仓库根目录，经 .venv-hub 解释器）：
  python -X utf8 eval/runner/run_eval.py --tier smoke|regression|full
  python -X utf8 eval/runner/run_eval.py --tier full --filter AP-PERM
  python -X utf8 eval/runner/run_eval.py --list

分层包含：smoke ⊂ regression ⊂ full（目标：冒烟 ≤3min）。
判官层（judge）与采样层另行启用（校准后），本层只做确定性断言。
写路径用例由 flow 驱动完整审批周期（approval_required -> 决定 -> resume）。

退出码：0 = 全部通过且零容忍门全绿；1 = 存在失败。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = ROOT / "eval" / "cases"
REPORTS_DIR = ROOT / "eval" / "reports"

GW = os.environ.get("GW_URL", "http://127.0.0.1:8000")
HUB = os.environ.get("HUB_URL", "http://127.0.0.1:8001")
PASSWORD = os.environ.get("GW_PASSWORD", "demo123")
INTERNAL = {"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "erp-demo-internal-secret")}

TIER_RANK = {"smoke": 0, "regression": 1, "full": 2}

# 零容忍类别：任一失败即整体不合格（披露 100% / 幻觉 0）
ZERO_TOLERANCE_CATEGORIES = ("AP-COMP", "AP-HALLU")
# 指标目标（写入报告；第一轮后可调）
TARGET_TOOL_RATE = 0.98
TARGET_PARAM_RATE = 0.95
TARGET_MAX_STEPS = 4


# ---------------------------------------------------------------- 用例加载
def load_cases(tier: str, filter_text: str | None) -> list[dict]:
    cases: list[dict] = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for case in data.get("cases") or []:
            cases.append(case)
    rank = TIER_RANK[tier]
    selected = [c for c in cases if TIER_RANK.get(c.get("tier"), 2) <= rank]
    if filter_text:
        selected = [c for c in selected if filter_text in c["id"]]
    selected.sort(key=lambda c: c["id"])
    return selected


# ---------------------------------------------------------------- 网关客户端
class Client:
    """登录缓存 + SSE 聊天 + 审批决定 + hub 唤醒。"""

    def __init__(self):
        self._tokens: dict[str, str] = {}
        self.http = httpx.Client(timeout=httpx.Timeout(15, read=180))

    def token(self, username: str) -> str:
        if username not in self._tokens:
            r = self.http.post(f"{GW}/gw/auth/sso/login",
                               json={"username": username, "password": PASSWORD})
            if r.status_code != 200:
                raise RuntimeError(f"login {username}: {r.status_code} {r.text[:120]}")
            self._tokens[username] = r.json()["token"]
        return self._tokens[username]

    def chat(self, username: str, message: str, scene: str, conversation_id: str) -> list[dict]:
        with httpx.stream("POST", f"{GW}/gw/chat/stream",
                          headers={"Authorization": f"Bearer {self.token(username)}"},
                          json={"message": message, "scene": scene,
                                "conversationId": conversation_id},
                          timeout=httpx.Timeout(30, read=180)) as resp:
            if resp.status_code != 200:
                body = resp.read()[:300].decode("utf-8", "replace")
                return [{"type": "error", "code": f"HTTP {resp.status_code}",
                         "message": body}]
            events = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))
        return events

    def decide(self, approver: str, approval_id: str, action: str) -> tuple[int, dict]:
        r = self.http.post(f"{GW}/gw/approvals/{approval_id}/decision",
                           headers={"Authorization": f"Bearer {self.token(approver)}"},
                           json={"action": action, "comment": f"eval {action}"})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"error": r.text[:200]}

    def resume(self, approval_id: str, one_time_token: str | None) -> tuple[int, dict]:
        r = self.http.post(f"{HUB}/internal/resume", headers=INTERNAL,
                           json={"approvalId": approval_id, "oneTimeToken": one_time_token})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"error": r.text[:200]}


# ---------------------------------------------------------------- 单用例执行
class Checks:
    def __init__(self):
        self.items: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append((name, bool(ok), "" if ok else detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.items)

    def failures(self) -> list[str]:
        return [f"{name} | {detail}" for name, ok, detail in self.items if not ok]


def _tool_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tool"]


def _answer_of(events: list[dict]) -> str:
    return "".join(e.get("text", "") for e in events if e.get("type") == "token")


def _error_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "error"]


def run_case(case: dict, client: Client, run_ts: str) -> dict:
    cid = case["id"]
    expect = case.get("expect") or {}
    checks = Checks()
    started = time.time()

    conv_id = f"eval-{cid}-{run_ts}"
    try:
        events = client.chat(case["user"], case["message"], case["scene"], conv_id)
    except Exception as e:  # noqa: BLE001 —— 网络层失败即用例失败
        return _result(case, checks, started, events=[], error=f"chat 异常：{e}")

    tools_ev = _tool_events(events)
    called = [e.get("tool") for e in tools_ev]
    answer = _answer_of(events)
    errors = _error_events(events)

    # 工具选择（子集匹配：期望工具必须被调用）
    for tool in expect.get("tools") or []:
        checks.add(f"tool:{tool}", tool in called, f"called={called}")
    # 禁调工具（零容忍：任何调用即失败）
    for tool in expect.get("forbidden_tools") or []:
        checks.add(f"forbidden:{tool}", tool not in called, f"called={called}")
    # 参数正确性（该工具的每次调用都须包含期望键值）
    for tool, argmap in (expect.get("tool_args") or {}).items():
        evs = [e for e in tools_ev if e.get("tool") == tool]
        if not evs:
            checks.add(f"args:{tool}", False, "工具未调用")
            continue
        for e in evs:
            args = e.get("arguments") or {}
            missing = {k: v for k, v in argmap.items() if args.get(k) != v}
            checks.add(f"args:{tool}", not missing, f"arguments={args} 期望包含={argmap}")
    # 工具错误码（如 applyTaxCode 首调必为 GW.APPROVAL_REQUIRED）
    for tool, code in (expect.get("tool_errors") or {}).items():
        evs = [e for e in tools_ev if e.get("tool") == tool]
        bad = [e.get("error") for e in evs if e.get("error") != code]
        checks.add(f"tool_error:{tool}", evs and not bad, f"errors={[e.get('error') for e in evs]}")
    # 步数上限
    max_steps = expect.get("max_tool_steps")
    if max_steps is not None:
        checks.add(f"steps<= {max_steps}", len(tools_ev) <= max_steps, f"steps={len(tools_ev)}")
    # 错误码
    want_code = expect.get("error_code", "NONE")
    if want_code == "NONE":
        checks.add("error:none", not errors, f"errors={[e.get('code') for e in errors]}")
    else:
        first = errors[0].get("code") if errors else None
        checks.add(f"error:{want_code}", first == want_code, f"first_error={first}")
    # 护栏规则 id
    want_rule = expect.get("error_rule")
    if want_rule:
        first_rule = errors[0].get("rule") if errors else None
        checks.add(f"rule:{want_rule}", first_rule == want_rule, f"first_rule={first_rule}")

    # 写路径：审批周期（挂起 -> 决定 -> 唤醒 -> 终态）
    flow = case.get("flow")
    if flow and flow.get("kind") == "taxcode_apply":
        approval_ev = next((e for e in events if e.get("type") == "approval_required"), None)
        checks.add("flow:approval_required", approval_ev is not None,
                   f"types={[e.get('type') for e in events]}")
        if approval_ev is None:
            return _result(case, checks, started, events=events)
        checks.add("flow:three-elements",
                   bool(approval_ev.get("approvalId") and approval_ev.get("rationale")
                        and approval_ev.get("impact")),
                   f"event={ {k: approval_ev.get(k) for k in ('approvalId', 'rationale', 'impact')} }")
        approval_id = approval_ev["approvalId"]
        action = "approve" if flow.get("decision") == "approve" else "reject"
        status, dec = client.decide(flow["approver"], approval_id, action)
        ok_dec = status == 200 and dec.get("status") == ("APPROVED" if action == "approve" else "REJECTED")
        checks.add(f"flow:decide:{action}", ok_dec, f"{status} {json.dumps(dec, ensure_ascii=False)[:160]}")
        ot = dec.get("oneTimeToken")
        rstatus, res = client.resume(approval_id, ot)
        checks.add("flow:resume", rstatus == 200 and res.get("ok") is True,
                   f"{rstatus} {json.dumps(res, ensure_ascii=False)[:200]}")
        want_result = flow.get("expect_result")
        if want_result:
            checks.add(f"flow:result:{want_result}", res.get("approvalResult") == want_result,
                       f"approvalResult={res.get('approvalResult')}")
        answer = (res.get("answer") or "") or answer

    # 回答内容（token 拼接或 resume 应答）
    for frag in expect.get("answer_contains") or []:
        checks.add(f"contains:{frag}", frag in answer, f"answer[:240]={answer[:240]}")
    for frag in expect.get("answer_not_contains") or []:
        checks.add(f"not_contains:{frag}", frag not in answer, f"answer[:240]={answer[:240]}")

    return _result(case, checks, started, events=events, answer=answer, called=called)


def _result(case: dict, checks: Checks, started: float, *, events: list[dict],
            answer: str = "", called: list | None = None, error: str | None = None) -> dict:
    if error:
        checks.add("chat", False, error)
    return {
        "id": case["id"], "title": case.get("title", ""),
        "category": case.get("category", ""), "tier": case.get("tier", ""),
        "ok": checks.ok, "failures": checks.failures(),
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks.items],
        "elapsed_ms": int((time.time() - started) * 1000),
        "tools_called": called or [], "steps": sum(1 for e in events if e.get("type") == "tool"),
        "answer_head": answer[:200],
    }


# ---------------------------------------------------------------- 汇总与报告
def summarize(results: list[dict], tier: str, total_seconds: float) -> dict:
    n = len(results)
    passed = [r for r in results if r["ok"]]
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += r["ok"]

    tool_cases = [r for r in results
                  if any(c["name"].startswith("tool:") for c in r["checks"])]
    tool_ok = [r for r in tool_cases if r["ok"]]
    param_cases = [r for r in results
                   if any(c["name"].startswith("args:") for c in r["checks"])]
    param_ok = [r for r in param_cases if r["ok"]]
    forbidden_hits = [c for r in results for c in r["checks"]
                      if c["name"].startswith("forbidden:") and not c["ok"]]
    max_steps_seen = max((r["steps"] for r in results), default=0)

    zero_tol_fail = [r["id"] for r in results
                     if r["category"] in ZERO_TOLERANCE_CATEGORIES and not r["ok"]]
    tool_rate = len(tool_ok) / len(tool_cases) if tool_cases else None
    param_rate = len(param_ok) / len(param_cases) if param_cases else None

    gates = {
        "zero_tolerance_pass": not zero_tol_fail,
        "forbidden_zero": not forbidden_hits,
        "tool_rate_target": tool_rate is None or tool_rate >= TARGET_TOOL_RATE,
        "param_rate_target": param_rate is None or param_rate >= TARGET_PARAM_RATE,
        "steps_target": max_steps_seen <= TARGET_MAX_STEPS,
    }
    return {
        "tier": tier, "total": n, "passed": len(passed), "failed": n - len(passed),
        "by_category": by_cat,
        "metrics": {
            "tool_correctness": tool_rate, "param_correctness": param_rate,
            "max_steps_seen": max_steps_seen,
            "forbidden_tool_violations": len(forbidden_hits),
            "zero_tolerance_failures": zero_tol_fail,
        },
        "gates": gates,
        "all_ok": n > 0 and n == len(passed) and all(gates.values()),
        "elapsed_seconds": round(total_seconds, 1),
        "cases": results,
    }


def write_reports(summary: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    tier = summary["tier"]
    (REPORTS_DIR / f"{tier}-latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    m = summary["metrics"]
    lines = [
        f"# 评测报告 · {tier} 档（确定性检查层）",
        "",
        f"- 用例：{summary['passed']}/{summary['total']} 通过，耗时 {summary['elapsed_seconds']}s",
        f"- 工具正确性：{m['tool_correctness'] if m['tool_correctness'] is not None else 'N/A'}"
        f"（目标 ≥{TARGET_TOOL_RATE}）",
        f"- 参数正确性：{m['param_correctness'] if m['param_correctness'] is not None else 'N/A'}"
        f"（目标 ≥{TARGET_PARAM_RATE}）",
        f"- 最大步数：{m['max_steps_seen']}（目标 ≤{TARGET_MAX_STEPS}）",
        f"- 禁调违规：{m['forbidden_tool_violations']}（目标 0）",
        f"- 零容忍失败：{m['zero_tolerance_failures'] or '无'}（AP-COMP/AP-HALLU 必须 100%）",
        "",
        "| 类别 | 通过/总数 |",
        "|---|---|",
    ]
    for cat in sorted(summary["by_category"]):
        c = summary["by_category"][cat]
        lines.append(f"| {cat} | {c['passed']}/{c['total']} |")
    lines += ["", "## 失败明细", ""]
    fails = [r for r in summary["cases"] if not r["ok"]]
    if not fails:
        lines.append("（无）")
    for r in fails:
        lines.append(f"### {r['id']} {r['title']}")
        for f in r["failures"]:
            lines.append(f"- {f}")
        lines.append("")
    (REPORTS_DIR / f"{tier}-latest.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 入口
def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="AP 锚点用例确定性评测")
    parser.add_argument("--tier", choices=list(TIER_RANK), default="smoke")
    parser.add_argument("--filter", default=None, help="按用例 id 子串过滤")
    parser.add_argument("--list", action="store_true", help="仅列出用例")
    args = parser.parse_args()

    cases = load_cases(args.tier, args.filter)
    if args.list:
        for c in cases:
            print(f"{c['id']:16s} {c['tier']:10s} {c['user']:10s} {c['scene']:10s} {c['title']}")
        print(f"\n共 {len(cases)} 条（tier={args.tier}）")
        return 0
    if not cases:
        print("无匹配用例")
        return 1

    print(f"评测 {len(cases)} 条用例（tier={args.tier}，GW={GW}）\n")
    client = Client()
    run_ts = str(int(time.time()))
    results = []
    started = time.time()
    for case in cases:
        r = run_case(case, client, run_ts)
        results.append(r)
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"{mark} {r['id']:16s} {r['elapsed_ms']:5d}ms {case['title']}")
        for f in r["failures"]:
            print(f"     - {f}")
    total_seconds = time.time() - started

    summary = summarize(results, args.tier, total_seconds)
    write_reports(summary)
    m, g = summary["metrics"], summary["gates"]
    print(f"\n{'=' * 60}")
    print(f"{summary['passed']}/{summary['total']} PASS，耗时 {total_seconds:.1f}s"
          f"（冒烟目标 ≤180s）")
    print(f"工具正确性 {m['tool_correctness']} | 参数 {m['param_correctness']} | "
          f"最大步数 {m['max_steps_seen']} | 禁调违规 {m['forbidden_tool_violations']}")
    print(f"零容忍失败 {m['zero_tolerance_failures'] or '无'}")
    print(f"门禁：{'全绿' if all(g.values()) else '存在未达标: ' + str(g)}")
    print(f"报告：{REPORTS_DIR / (args.tier + '-latest.md')}")
    return 0 if summary["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
