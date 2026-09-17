#!/usr/bin/env python3
"""Agent 形态③：无头 MCP 脚本（headless CLI）。

不经 hub/LLM，脚本以后端客户凭据换 T2，直接经网关 /gw/mcp 调工具 ——
演示「无头链路同样受网关全链路拦截（注册/吊销/scope/租户）」。

用法:
  python scripts/headless_mcp.py list  [--agent ap-headless] [--scene ap.batch]
                                       [--user zhangsan] [--tenant T-EAST]
  python scripts/headless_mcp.py call <tool> [--args '{"invoiceNo": "INV-A-001"}']
                                       [--agent ...] [--scene ap.diag]
                                       [--user ...] [--tenant ...]

示例:
  python scripts/headless_mcp.py list
  python scripts/headless_mcp.py call ap.invoice.checkValidation --args '{"invoiceNo":"INV-A-001"}'
  python scripts/headless_mcp.py call semantic.term.translate --args '{"term":"进货单"}'

退出码: 0 = 成功；1 = 工具被拒/业务失败；2 = 服务不可达或参数错误。
"""
from __future__ import annotations

import argparse
import json
import sys

import _common as C

# 各 agent 默认绑定的场景与身份（与网关注册表/场景白名单一致）
DEFAULTS = {
    "ap-headless": ("ap.batch", "zhangsan", "T-EAST"),
    "ap-copilot": ("ap.diag", "zhangsan", "T-EAST"),
    "uni-copilot": ("ap.diag", "zhaoliu", "T-UNI"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="无头 MCP CLI（形态③：脚本 -> 网关 -> BO API/语义工具）")
    ap.add_argument("command", choices=["list", "call"], help="list=列出场景内可见工具；call=调用工具")
    ap.add_argument("tool", nargs="?", help="工具名（call 必填）")
    ap.add_argument("--args", default="{}", help="工具参数 JSON（默认 {}）")
    ap.add_argument("--agent", default="ap-headless", help="Agent ID（默认 ap-headless）")
    ap.add_argument("--scene", default=None, help="场景（默认按 agent 推断）")
    ap.add_argument("--user", default=None, help="代表用户（默认按 agent 推断）")
    ap.add_argument("--tenant", default=None, help="租户（默认按 agent 推断）")
    args = ap.parse_args()

    if args.command == "call" and not args.tool:
        print("[headless] call 需要工具名", file=sys.stderr)
        return 2
    try:
        tool_args = json.loads(args.args)
    except ValueError as e:
        print(f"[headless] --args 不是合法 JSON：{e}", file=sys.stderr)
        return 2

    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[headless] 服务不可达：{down} —— 请先启动 compose", file=sys.stderr)
        return 2

    d_scene, d_user, d_tenant = DEFAULTS.get(args.agent, ("ap.diag", "zhangsan", "T-EAST"))
    scene = args.scene or d_scene
    user = args.user or d_user
    tenant = args.tenant or d_tenant

    # ---- 换 T2（拦截链在网关：未注册/吊销/租户不符/SoD 在此即被拒） ----
    # call：按单工具收窄请求 scope（逐跳收窄演示）；list：以场景代表工具探测
    requested = [args.tool] if args.command == "call" else ["ap.invoice.listBlocked"]
    print(f"[headless] 令牌交换：agent={args.agent} scene={scene} user={user} tenant={tenant}"
          f" tools={requested}")
    try:
        t2 = C.exchange(args.agent, scene, requested, user, tenant)
    except C.GwError as e:
        print(f"[headless] 交换被拒 -> {e.code}: {e.message}")
        return 1
    print("[headless] T2 获取成功")

    # ---- list ----
    if args.command == "list":
        tools = C.mcp_list(t2)
        print(f"[headless] 场景 {scene} 可见工具 {len(tools)} 个：")
        for t in tools:
            desc = (t.get("description") or "").strip().splitlines()
            print(f"  - {t.get('name')}  {''.join(desc[:1])}")
        return 0

    # ---- call ----
    print(f"[headless] tools/call {args.tool} {json.dumps(tool_args, ensure_ascii=False)}")
    try:
        # 携带单工具 scope 再换一次 T2（与网关 T3 单工具收窄同向；换 T2 传空则沿用场景全集）
        result = C.mcp_call(t2, args.tool, tool_args)
    except C.GwToolError as e:
        print(f"[headless] 调用被拒 -> {e.code}: {e.message}")
        if e.remediation:
            print(f"[headless] remediation: {json.dumps(e.remediation, ensure_ascii=False)}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
