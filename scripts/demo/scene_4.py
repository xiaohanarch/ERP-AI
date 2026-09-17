#!/usr/bin/env python3
"""第 4 幕：未注册 / 吊销 —— Agent 生命周期即访问边界。

  1) 未注册 Agent 换令牌 → GW.AGENT_NOT_REGISTERED；
  2) 吊销 ap-headless → 既有 T2 下次调用即 401 GW.AGENT_REVOKED（即时生效）；
  3) 恢复（演示复位）→ 交换与调用恢复正常。

用法: python scripts/demo/scene_4.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402


def main() -> int:
    print("=== 第 4 幕：未注册 / 吊销 —— Agent 生命周期即访问边界 ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_4] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 4 幕")

    # ---- 1) 未注册 ----
    print("── 未注册 Agent（rogue-agent）换令牌")
    try:
        C.exchange("rogue-agent", "ap.diag", ["ap.invoice.checkValidation"], "zhangsan", "T-EAST")
        ck.add("未注册 Agent 被拒（GW.AGENT_NOT_REGISTERED）", False, "未被拒绝")
    except C.GwError as e:
        print(f"  被拒：{e.code}: {e.message}")
        ck.add("未注册 Agent 被拒（GW.AGENT_NOT_REGISTERED）",
               e.code == "GW.AGENT_NOT_REGISTERED", f"{e.code}: {e.message}")

    # ---- 2) 吊销即时生效 ----
    print("── 吊销 ap-headless（先持有一张在期 T2）")
    t2 = C.exchange("ap-headless", "ap.batch", ["ap.invoice.listBlocked"], "zhangsan", "T-EAST")
    before = C.mcp_call(t2, "ap.invoice.listBlocked", {"pageSize": 5})
    ck.add("吊销前调用正常", before["pageInfo"]["total"] > 0, f"total={before['pageInfo']['total']}")

    C.gw_post("/gw/agents/ap-headless/revoke")
    roster = C.gw_get("/gw/agents")
    status = next((a.get("status") for a in roster["agents"] if a["agentId"] == "ap-headless"), None)
    print(f"  清册状态：{status}")
    ck.add("清册显示 REVOKED", status == "REVOKED", f"status={status}")

    try:
        C.mcp_call(t2, "ap.invoice.listBlocked", {"pageSize": 5})
        ck.add("既有 T2 下次调用即拒（GW.AGENT_REVOKED）", False, "未被拒绝")
    except C.GwToolError as e:
        print(f"  既有 T2 被拒：{e.code}: {e.message}")
        ck.add("既有 T2 下次调用即拒（GW.AGENT_REVOKED）", e.code == "GW.AGENT_REVOKED",
               f"{e.code}: {e.message}")

    try:
        C.exchange("ap-headless", "ap.batch", ["ap.invoice.listBlocked"], "zhangsan", "T-EAST")
        ck.add("吊销后新交换同样被拒", False, "未被拒绝")
    except C.GwError as e:
        ck.add("吊销后新交换同样被拒", e.code == "GW.AGENT_REVOKED", f"{e.code}: {e.message}")

    # ---- 3) 恢复（演示复位） ----
    print("── 恢复 ap-headless（演示复位）")
    C.gw_post("/gw/agents/ap-headless/restore")
    t2b = C.exchange("ap-headless", "ap.batch", ["ap.invoice.listBlocked"], "zhangsan", "T-EAST")
    after = C.mcp_call(t2b, "ap.invoice.listBlocked", {"pageSize": 5})
    ck.add("恢复后交换与调用正常", after["pageInfo"]["total"] > 0,
           f"total={after['pageInfo']['total']}")

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
