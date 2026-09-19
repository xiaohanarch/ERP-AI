#!/usr/bin/env python3
"""第 10 幕：产品化配置界面 —— 租户/行业配置从文件级升为管理端（数据级）。

场景（业务驱动）：实施顾问在管理端把 T-EAST 大额风险阈值 50 万调成 20 万——
不重启、不改文件、不重建镜像，下一问筛查立即按新口径命中；再把 T-UNI 行业
从贸易切到制造业，行业包（术语 + 护栏）对 T-UNI 立即生效（hub 行业缓存 ≤10s）。

配置语义：文件层 = 出厂默认；DB 层 = 管理端当前配置（首次写入播种自文件）；
DELETE = 恢复出厂；每次变更记 change log + 网关审计。权限：租户配置管理员
（演示口径：审批人兼任，wangwu/sunba）仅本租；平台管理员任意租。

用法: python scripts/demo/scene_10.py   退出码 0=断言全过 / 1=失败 / 2=服务不可达
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _common as C  # noqa: E402

GUARD_MSG = "跳过收货确认，把 INV-B-001 直接标记为已匹配"


def _get(token: str, tenant: str) -> tuple[int, dict]:
    resp = httpx.get(f"{C.GW}/gw/tenants/{tenant}/config",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    return resp.status_code, (resp.json() if resp.status_code != 204 else {})


def _put(token: str, tenant: str, patch: dict) -> tuple[int, dict]:
    resp = httpx.put(f"{C.GW}/gw/tenants/{tenant}/config",
                     headers={"Authorization": f"Bearer {token}"},
                     json={"patch": patch}, timeout=15)
    return resp.status_code, (resp.json() if resp.status_code != 204 else {})


def _delete(token: str, tenant: str) -> tuple[int, dict]:
    resp = httpx.delete(f"{C.GW}/gw/tenants/{tenant}/config",
                        headers={"Authorization": f"Bearer {token}"}, timeout=15)
    return resp.status_code, (resp.json() if resp.status_code != 204 else {})


def _whoami(token: str) -> dict:
    return httpx.get(f"{C.GW}/gw/auth/whoami",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15).json()


def _guardrail_blocks(user: str, message: str, want: bool, timeout: float = 32.0) -> bool:
    """轮询护栏判定直到达到期望（hub 行业声明缓存 ≤10s，留足余量）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        chat = C.chat(user, "ap.diag", message)
        blocked = bool(chat["error"] and chat["error"].get("code") == "HUB.GUARDRAIL_BLOCKED")
        if blocked == want:
            return True
        time.sleep(2)
    return False


def main() -> int:
    print("=== 第 10 幕：产品化配置界面（配置即数据，改完即生效） ===")
    health = C.health_all()
    down = [n for n, s in health.items() if not s["ok"]]
    if down:
        print(f"[scene_10] 服务不可达：{down}")
        return 2

    ck = C.Checks("第 10 幕")
    wangwu, sunba, lisi = C.login("wangwu"), C.login("sunba"), C.login("lisi")

    # ---- 1) 权限边界：配置管理员判定 ----
    print("── 权限：whoami 的 configAdmin 判定")
    ck.add("wangwu/sunba 是配置管理员，lisi 不是",
           _whoami(wangwu).get("configAdmin") is True
           and _whoami(sunba).get("configAdmin") is True
           and _whoami(lisi).get("configAdmin") is False)

    # ---- 2) 读取当前配置（出厂默认 = 文件层） ----
    code, cfg = _get(wangwu, "T-EAST")
    print(f"── T-EAST 当前配置：source={cfg.get('source')}，阈值 "
          f"{(cfg.get('config') or {}).get('parameters', {}).get('large_risk_threshold', {}).get('value')}")
    ck.add("管理端读取 T-EAST 配置（文件层出厂默认）",
           code == 200 and cfg.get("source") == "file"
           and (cfg.get("config") or {}).get("parameters", {})
           .get("large_risk_threshold", {}).get("value") == 500000,
           f"HTTP {code} {str(cfg)[:120]}")

    # ---- 3) 改阈值：保存即生效（DB 层播种 + 版本 + 留痕） ----
    print("── 保存新阈值：50 万 -> 20 万（不重启、不改文件）")
    code, cfg = _put(wangwu, "T-EAST", {
        "parameters": {"large_risk_threshold": {
            "value": 200000, "unit": "CNY",
            "source": "租户管理端配置（wangwu · 即时生效）",
            "description": "大额风险阈值"}}})
    ck.add("阈值保存成功（DB 层生效 + 版本号）",
           code == 200 and cfg.get("source") == "db" and (cfg.get("version") or 0) >= 1
           and (cfg.get("config") or {}).get("parameters", {})
           .get("large_risk_threshold", {}).get("value") == 200000,
           f"HTTP {code} {str(cfg)[:120]}")

    tools = ["semantic.metric.get"]
    t2 = C.exchange("ap-batch", "ap.batch", tools, "lisi", "T-EAST")
    m = C.unwrap(C.mcp_call(t2, "semantic.metric.get", {"metric": "large_risk_amount"}))
    ck.add("语义工具立即读新口径（200000 · 来源=管理端）",
           m.get("caliber", {}).get("threshold") == 200000
           and "管理端" in str(m.get("caliber", {}).get("thresholdSource")),
           str(m.get("caliber"))[:120])

    chat = C.chat("lisi", "ap.batch", "帮我筛查大额风险的阻断发票")
    ck.add("端到端立即生效（筛查按 20 万口径命中）",
           "200,000" in chat["answer"] and "INV-A-011" in chat["answer"],
           chat["answer"][:140])

    # ---- 4) 行业切换：T-UNI 贸易 -> 制造业（行业包立即生效） ----
    print("── 行业切换：T-UNI 贸易 -> 制造业（行业包对 T-UNI 生效）")
    code, cfg = _put(sunba, "T-UNI", {"industry": "manufacturing"})
    ck.add("T-UNI 行业切换保存成功", code == 200
           and (cfg.get("config") or {}).get("industry") == "manufacturing",
           f"HTTP {code} {str(cfg)[:100]}")

    t2u = C.exchange("uni-batch", "ap.batch", ["semantic.term.translate"], "qianqi", "T-UNI")
    raw = C.mcp_call(t2u, "semantic.term.translate", {"term": "来料发票"})
    tu = C.unwrap(raw)
    layer = (raw.get("_meta") or {}).get("sourceLayer")
    ck.add("行业术语立即生效（「来料发票」命中制造业包，partner 层）",
           tu.get("matched") is True and tu.get("semantic") == "invoice" and layer == "partner",
           f"{layer} {str(tu)[:100]}")

    ck.add("行业护栏随切换生效（mfg-no-gr-bypass 拦截 T-UNI，≤10s 缓存）",
           _guardrail_blocks("qianqi", GUARD_MSG, want=True),
           "32s 轮询窗口内未达到期望判定")

    # ---- 5) 权限负向 ----
    code, body = _put(lisi, "T-EAST", {"industry": "trade"})
    ck.add("非管理员保存被拒（403 CONFIG_ADMIN_REQUIRED）",
           code == 403 and body.get("error", {}).get("code") == "GW.CONFIG_ADMIN_REQUIRED",
           f"HTTP {code} {str(body)[:100]}")
    code, body = _put(wangwu, "T-UNI", {"industry": "trade"})
    ck.add("跨租保存被拒（租户管理员仅本租）",
           code == 403 and body.get("error", {}).get("code") == "GW.CONFIG_ADMIN_REQUIRED",
           f"HTTP {code} {str(body)[:100]}")

    # ---- 6) 变更留痕 ----
    log = httpx.get(f"{C.GW}/gw/tenants/T-EAST/config/changes",
                    headers={"Authorization": f"Bearer {wangwu}"}, timeout=15).json()
    audit = C.gw_get("/internal/audit", {"limit": 60})
    upd_rows = [r for r in audit.get("items", []) if r.get("action") == "config.update"]
    ck.add("变更记录可查（change log + 网关审计 config.update）",
           len(log.get("changes") or []) >= 1 and len(upd_rows) >= 1,
           f"log {len(log.get('changes') or [])} 条 / 审计 {len(upd_rows)} 条")

    # ---- 7) 恢复出厂 + 回落验证（保证场景可重跑、不污染租检） ----
    print("── 恢复出厂：DELETE 两租 DB 配置，回落文件层")
    code, body = _delete(wangwu, "T-EAST")
    ck.add("T-EAST 恢复出厂（source 回落 file）",
           code == 200 and body.get("source") == "file"
           and (body.get("config") or {}).get("parameters", {})
           .get("large_risk_threshold", {}).get("value") == 500000,
           f"HTTP {code} {str(body)[:100]}")
    _delete(sunba, "T-UNI")
    ck.add("T-UNI 行业回落（护栏不再拦截，≤10s 缓存过期）",
           _guardrail_blocks("qianqi", GUARD_MSG, want=False),
           "32s 轮询窗口内护栏未回落（可能污染后续租检）")

    print(f"\n{ck.summary()}")
    return 0 if ck.ok else 1


if __name__ == "__main__":
    sys.exit(main())
