#!/usr/bin/env python3
"""第 6 幕：审批留痕 + 证据包 + 五分钟自检（写路径全生命周期）。

李四请求补全 INV-A-052 税码 → 网关见 irreversible 建 approval_task 并返回
GW.APPROVAL_REQUIRED → hub interrupt 挂起（三要素：打算做什么/依据/影响）→
王五批准（快照留痕 + 一次性令牌 OT）→ hub 唤醒重发（幂等键不变）→ 落库 →
导出 T-EAST 证据包（委托链 + 审批快照 + 审计摘录）→ 五分钟自检四问可答。

用法: python scripts/demo/scene_6.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402


def main() -> int:
    print("=== 第 6 幕：审批留痕 + 证据包 + 五分钟自检 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_6] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 6 幕")

    # ---- 1) 写请求挂起（approval_required 三要素） ----
    print("── 李四（WorkBuddy）请求：把 INV-A-052 的税码补全为 CN-VAT-13")
    chat = C.chat("lisi", "ap.taxcode", "把 INV-A-052 的税码补全为 CN-VAT-13",
                  conversation_id=C.new_cid("scene6"))
    ap_ev = chat["approval"]
    ck.add("写路径挂起（approval_required 事件）", ap_ev is not None,
           f"error={chat['error']}")
    if ap_ev is None:
        print(f"\n{ck.summary()}")
        return 1
    approval_id = ap_ev["approvalId"]
    print(f"  审批单：{approval_id}")
    print(f"  建议：{str(ap_ev.get('suggestion'))[:100]}")
    print(f"  依据：{str(ap_ev.get('rationale'))[:100]}")
    print(f"  影响：{str(ap_ev.get('impact'))[:100]}")
    ck.add("三要素齐备（suggestion / rationale / impact）",
           bool(ap_ev.get("suggestion") and ap_ev.get("rationale") and ap_ev.get("impact")))

    # ---- 2) 审批人视角：任务详情含快照 ----
    print("── 王五（审批人）查看审批任务")
    detail = C.approval_detail(approval_id, "wangwu")
    snap = detail.get("snapshot") or detail.get("paramsSnapshot") or {}
    ck.add("审批详情含快照（确认人当时所见）", bool(snap), str(list(detail.keys())))
    print(f"  状态：{detail.get('status')}；快照键：{list(snap)[:6] if snap else '无'}")

    # ---- 3) 批准 -> OT -> 唤醒 -> 落库 ----
    print("── 王五批准（铸一次性令牌 OT）")
    dec = C.decide(approval_id, "wangwu", "approve", "同意按建议补全")
    ot = dec.get("oneTimeToken")
    ck.add("批准返回 oneTimeToken", bool(ot), f"status={dec.get('status')}")

    print("── hub 审批唤醒（携 OT 重发，幂等键不变）")
    res = C.resume(approval_id, ot)
    answer = res.get("answer") or ""
    ck.add("唤醒成功且写操作落库", res.get("ok") is True
           and res.get("approvalResult") == "applied",
           f"approvalResult={res.get('approvalResult')}")
    # 首次执行引用本次审批单号；重复执行命中业务幂等，重放首次结果（引用原审批单号）
    ck.add("应答明示完成 + 审批人 + 审批单号（或幂等重放）",
           "税码变更已完成" in answer and "审批人" in answer
           and (approval_id in answer or "幂等重放：是" in answer),
           answer[:120])
    print(f"  应答（截断）：{answer[:140]}")

    # ---- 4) 证据包导出（含委托链 + 审批快照） ----
    print("── 导出 T-EAST 证据包（近 24 小时）")
    evd = C.gw_get("/gw/evidence/export", {"tenant_id": "T-EAST", "hours": 24})
    approvals = evd.get("approvals") or []
    mine = next((a for a in approvals if a.get("approvalId") == approval_id), None)
    ck.add("证据包含本次审批（approver + snapshot）",
           bool(mine and mine.get("approver") == "wangwu" and mine.get("snapshot")),
           f"共 {len(approvals)} 条审批")
    ck.add("证据包含版本四件套", bool(evd.get("versions")), str(evd.get("versions")))
    print(f"  审批 {len(approvals)} 条；审计摘录 {len(evd.get('auditExcerpt') or [])} 条；"
          f"版本：{json.dumps(evd.get('versions'), ensure_ascii=False)}")

    # ---- 5) 五分钟自检（四问） ----
    print("── 五分钟自检（selfcheck 四问）")
    proc = subprocess.run([sys.executable, "-X", "utf8",
                           str(Path(C.REPO) / "scripts" / "selfcheck.py")],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(C.REPO), timeout=300)
    ck.add("自检四问全部可答", proc.returncode == 0,
           (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else "无输出")
    print(f"  退出码 {proc.returncode}；报告 -> docs/selfcheck-latest.md")

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
