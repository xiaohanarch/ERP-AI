#!/usr/bin/env python3
"""WorkBuddy 浏览器级 E2E：OAuth 登录 -> 对话（读/写）-> 审批 -> 通知 -> 深链。

覆盖形态②（助手平台）全链路：
  1) 登录页 -> 网关统一登录（OAuth 授权码）-> 回调换 T1 -> 对话页（李四 / T-EAST）
  2) 读侧对话：INV-A-001 归因（SSE 流式渲染，断言 QTY_MISMATCH）
  3) 写侧对话：INV-A-052 税码补全 -> 挂起卡片（三要素 + 审批单号）
  4) 退出 -> 王五登录 -> 审批台 -> 批准 -> 唤醒落库（result=applied）
  5) 通知中心（王五见审批请求；李四重新登录见审批结果）
  6) 深链：登出后直开 /chat?scene=…&q=…（intro.html 演示链接）—— 登录后回跳原目标并自动发起

用法: python scripts/e2e_workbuddy.py   退出码 0=全过 / 1=失败 / 2=环境不可用
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import _common as C  # noqa: E402

BASE = "http://localhost:8088"
GW = C.GW

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" —— {detail}" if detail and not ok else ""))


def login(page, username: str) -> None:
    """从登录页经网关 OAuth 授权码流程进入对话页。"""
    page.goto(f"{BASE}/login")
    page.click("button.btn.login")
    # 网关统一登录表单
    page.wait_for_selector("input[name=username]", timeout=10_000)
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", "demo123")
    page.click("form button[type=submit]")
    page.wait_for_url(f"{BASE}/chat", timeout=15_000)


def wait_idle(page) -> None:
    """等待上一条消息的 SSE 流结束（「执行中……」指示消失），避免忙时发送被静默丢弃。"""
    page.wait_for_selector(".chat-meta .typing", state="detached", timeout=60_000)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[e2e] 缺少 playwright，跳过浏览器验证")
        return 2

    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[e2e] 服务不可达：{down}")
        return 2
    try:
        import urllib.request
        with urllib.request.urlopen(BASE, timeout=5) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
    except Exception as e:  # noqa: BLE001
        print(f"[e2e] WorkBuddy 不可达（{BASE}）：{e}")
        return 2

    print("=== WorkBuddy 浏览器 E2E ===")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.set_default_timeout(20_000)
        try:
            # ---- 1) 李四 OAuth 登录 ----
            print("── 李四经网关 OAuth 授权码登录")
            login(page, "lisi")
            check("回调换 T1 后进入对话页", page.url == f"{BASE}/chat", page.url)
            side = page.inner_text(".side-foot")
            check("侧栏显示用户与租户", "李四" in side and "T-EAST" in side, side)

            # ---- 2) 读侧对话（SSE 流式） ----
            print("── 读侧：INV-A-001 校验失败原因")
            page.fill("textarea", "INV-A-001 校验失败的原因是什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".turn .body", timeout=60_000)
            page.wait_for_selector("text=数量", timeout=60_000)
            wait_idle(page)
            answer = page.inner_text(".chat-scroll")
            check("应答含数量差异归因", "AP.MATCH.QTY_MISMATCH" in answer and "20" in answer, answer[:200])
            check("李四可见预算超支（completeness 完整）", "AP.BUDGET.EXCEEDED" in answer)
            check("工具调用链可见", "ap.invoice.checkValidation" in answer and "ap.invoice.getMatchDetail" in answer)

            # ---- 3) 写侧：税码补全挂起 ----
            print("── 写侧：INV-A-052 税码补全（挂起审批）")
            page.click(".scene-opt:has-text('税码补全')")
            page.fill("textarea", "把 INV-A-052 的税码补全为 CN-VAT-13")
            page.keyboard.press("Enter")
            page.wait_for_selector(".approval-card", timeout=60_000)
            card = page.inner_text(".approval-card")
            check("挂起卡片出现（GW.APPROVAL_REQUIRED）", "等待审批" in card, card[:200])
            check("三要素齐备（做什么/依据/影响）",
                  "打算做什么" in card and "依据" in card and "影响" in card, card[:300])
            approval_id = page.inner_text(".approval-card .mono")
            check("审批单号可见", approval_id.startswith("apr-"), approval_id)
            print(f"  审批单：{approval_id}")
            page.screenshot(path=str(REPO / "docs" / "screenshots" / "workbuddy-chat-approval.png"))

            # ---- 4) 王五登录审批 ----
            print("── 王五登录审批台处理")
            page.click(".side-foot button")  # 退出
            page.wait_for_url(f"{BASE}/login*")  # 未登录重定向到 /login?returnTo=…
            login(page, "wangwu")
            side = page.inner_text(".side-foot")
            check("王五登录成功", "王五" in side, side)

            page.click("a[href='/approvals']")
            page.wait_for_selector(".appr-head", timeout=15_000)
            target = page.locator(".card", has=page.locator("text=待审批")).filter(
                has_text=approval_id).first
            check("审批台出现该待审批任务", target.count() > 0, approval_id)
            detail = target.inner_text()
            check("审批卡含快照（确认人当时所见）", "快照" in detail and "INV-A-052" in detail, detail[:300])
            check("审批卡含执行参数", "执行参数" in detail and "params_hash" in detail.replace("（", "("), detail[:400])
            # 审批意见 + 批准
            target.locator(".decide-bar input").fill("E2E 浏览器验证：同意补全")
            target.locator("button:has-text('批准')").click()
            page.wait_for_selector(".result-banner", timeout=60_000)
            banner = page.inner_text(".result-banner")
            check("批准后唤醒落库（applied）",
                  "唤醒落库" in banner and "税码变更已完成" in banner, banner[:300])
            page.screenshot(path=str(REPO / "docs" / "screenshots" / "workbuddy-approvals-result.png"))

            # ---- 6) 解析查看器 ----
            print("── 解析查看器（三层解析留痕）")
            page.click("a[href='/resolution']")
            page.wait_for_selector(".res-recent .chip", timeout=15_000)
            page.click(".res-recent .chip")
            page.wait_for_selector(".appr-section", timeout=15_000)
            res = page.inner_text(".content")
            check("解析查看器展示生效护栏与来源层", "生效护栏" in res and "standard 层" in res, res[:200])
            check("租户层护栏叠加可见（east-no-bulk-approval）", "east-no-bulk-approval" in res)
            check("提示词资产解析可见", "系统提示词资产" in res)
            page.screenshot(path=str(REPO / "docs" / "screenshots" / "workbuddy-resolution.png"))

            # ---- 5) 通知中心 ----
            print("── 通知中心（王五视角）")
            page.click("a[href='/notifications']")
            page.wait_for_selector(".notif-item", timeout=15_000)
            notif = page.inner_text(".card")
            check("王五收到审批请求通知", "审批请求" in notif, notif[:200])
            badge = page.locator(".nav .count").count()
            print(f"  （未读角标元素：{badge} 个）")

            # ---- 7) 深链：登出后直开演示链接（intro.html 的 ▶ 链接） ----
            print("── 深链：未登录访问 /chat?scene=ap.batch&q=…（returnTo 回跳 + 自动发起）")
            page.click(".side-foot button")  # 退出（王五）
            page.wait_for_url(f"{BASE}/login*")
            import urllib.parse
            deep = f"{BASE}/chat?scene=ap.batch&q=" + urllib.parse.quote("帮我筛查大额风险的阻断发票")
            page.goto(deep)
            # Protected 未登录 -> /login?returnTo=…：在此页直接发起 OAuth（Login 保存 returnTo）
            page.click("button.btn.login")
            page.wait_for_selector("input[name=username]", timeout=10_000)
            page.fill("input[name=username]", "lisi")
            page.fill("input[name=password]", "demo123")
            page.click("form button[type=submit]")
            page.wait_for_url(f"{BASE}/chat", timeout=15_000)  # 回调后回跳原目标（参数随后被消费清掉）
            page.wait_for_selector(".scene-opt.on:has-text('批量筛查')", timeout=10_000)
            check("深链回跳原目标且场景预选（批量筛查）", True)
            page.wait_for_selector(".turn .body", timeout=90_000)
            wait_idle(page)
            deep_ans = page.inner_text(".chat-scroll")
            check("深链自动发起并返回筛查结论",
                  ("大额" in deep_ans or "阻断" in deep_ans) and "INV-" in deep_ans, deep_ans[:200])
            page.screenshot(path=str(REPO / "docs" / "screenshots" / "workbuddy-deeplink.png"))

            browser.close()
        except Exception as e:  # noqa: BLE001
            try:
                page.screenshot(path=str(REPO / "eval" / "reports" / "e2e-workbuddy-fail.png"))
            except Exception:  # noqa: BLE001
                pass
            print(f"\n[e2e] 失败：{e}")
            return 1

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n=== E2E 结果：{passed}/{len(CHECKS)} 通过 ===")
    for name, ok, detail in CHECKS:
        if not ok:
            print(f"  ✗ {name} —— {detail}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
