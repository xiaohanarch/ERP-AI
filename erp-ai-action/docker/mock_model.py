#!/usr/bin/env python3
"""mock 模型：OpenAI 兼容 /v1/chat/completions 脚本化确定性应答。

设计要点：
  - 确定性（同输入同输出），供评测回放与冒烟；
  - 场景感知（请求体携带 scene 扩展字段），按场景输出「下一步动作 JSON」，
    由 hub 解析后驱动工具调用 —— mock 只负责拟态，不做任何权限判定；
  - 诱导类输入（如"帮我付款"）不产生付款意图：判定权在网关与存量系统。

应答 content 约定（hub 解析）：
  ap.diag    -> {"intent":"diagnose","invoiceNo":"INV-A-001","reply":"..."}
  ap.batch   -> {"intent":"batch_screen","reply":"..."}
  ap.taxcode -> {"intent":"suggest_tax_code","invoiceNo":"...","taxCode":"...","reason":"..."}
  ap.event   -> {"intent":"event_summary","summary":"..."}（无头诊断归因摘要，输入为校验取证结果）
  proc.diag  -> {"intent":"po_lookup","poNo":"PO-A-0001","reply":"..."}
  xdom.diag  -> {"intent":"diagnose_cross","invoiceNo":"...","reply":"..."}
  无单号     -> {"intent":"clarify","reply":"请提供发票号/采购订单号..."}
"""
from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INVOICE_NO = re.compile(r"INV-[A-Z0-9\-]+")
PO_NO = re.compile(r"PO-[A-Z0-9\-]+")
RULESET_VERSION = "AP-RS-1.2.0"


def extract_po(messages: list[dict]) -> str | None:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            found = PO_NO.search(m.get("content", ""))
            if found:
                return found.group(0)
    return None


def extract_invoice(messages: list[dict]) -> str | None:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            found = INVOICE_NO.search(m.get("content", ""))
            if found:
                return found.group(0)
    return None


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def scripted_content(scene: str, messages: list[dict]) -> str:
    inv = extract_invoice(messages)
    po = extract_po(messages)
    text = last_user_text(messages)

    if scene == "ap.batch":
        return json.dumps({
            "intent": "batch_screen",
            "reply": "好的，我来筛查当前权限范围内被阻断的发票，并统计主要原因。",
        }, ensure_ascii=False)

    if scene == "proc.diag":
        if po:
            return json.dumps({
                "intent": "po_lookup",
                "poNo": po,
                "reply": f"好的，我查询采购订单 {po} 的详情与收货情况。",
            }, ensure_ascii=False)
        return json.dumps({
            "intent": "clarify",
            "reply": "请提供采购订单号（如 PO-A-0001）。",
        }, ensure_ascii=False)

    if scene == "xdom.diag":
        if inv:
            return json.dumps({
                "intent": "diagnose_cross",
                "invoiceNo": inv,
                "reply": f"好的，我对发票 {inv} 做跨域归因：先 AP 侧诊断，再委派采购域取证。",
            }, ensure_ascii=False)
        return json.dumps({
            "intent": "clarify",
            "reply": "请提供发票号（如 INV-A-001）。",
        }, ensure_ascii=False)

    if scene == "ap.taxcode":
        if inv:
            return json.dumps({
                "intent": "suggest_tax_code",
                "invoiceNo": inv,
                "taxCode": "CN-VAT-13",
                "reason": f"发票 {inv} 的供应商位于江苏，依据规则 {RULESET_VERSION} 的税码建议（AP.TAX.CODE_SUGGESTED），建议适用 13% 增值税码。",
                "reply": f"根据供应商所在地常用税码，建议将 {inv} 的税码调整为 CN-VAT-13。是否提交申请？（提交后将进入审批流程）",
            }, ensure_ascii=False)
        return json.dumps({
            "intent": "clarify",
            "reply": "请提供需要补全税码的发票号（如 INV-A-003）。",
        }, ensure_ascii=False)

    if scene == "ap.event":
        if "已阻断" in text:  # 归因摘要请求：用户消息为确定性校验取证结果
            return json.dumps({
                "intent": "event_summary",
                "summary": (f"发票 {inv} 的阻断主因是数量差异与预算校验（依据校验发现，"
                            f"规则集 {RULESET_VERSION}）；建议先核对收货数量，"
                            "再确认预算余额后重新提交。" if inv else
                            "阻断主因是数量差异与预算校验（依据校验发现）；"
                            "建议先核对收货数量，再确认预算余额后重新提交。"),
            }, ensure_ascii=False)
        if inv:
            return json.dumps({
                "intent": "event_diag",
                "invoiceNo": inv,
                "reply": f"收到发票阻断事件，开始对 {inv} 执行归因诊断。",
            }, ensure_ascii=False)
        return json.dumps({"intent": "clarify", "reply": "事件缺少发票号。"}, ensure_ascii=False)

    # 默认 ap.diag（诊断）
    if inv:
        return json.dumps({
            "intent": "diagnose",
            "invoiceNo": inv,
            "reply": f"好的，我对发票 {inv} 执行校验并归因阻断原因。",
        }, ensure_ascii=False)
    if "大额" in text or "风险" in text:
        return json.dumps({
            "intent": "large_risk",
            "reply": "好的，我按当前租户的大额风险口径筛查发票。",
        }, ensure_ascii=False)
    return json.dumps({
        "intent": "clarify",
        "reply": "请提供发票号（如 INV-A-001），或描述要筛查的范围。",
    }, ensure_ascii=False)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 精简日志
        print(f"[mock-model] {self.path}", flush=True)

    def _json(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._json(200, {"object": "list", "data": [{"id": "mock-scene-model", "object": "model"}]})
        if self.path == "/healthz":
            return self._json(200, {"status": "ok"})
        return self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._json(404, {"error": {"message": "not found"}})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": {"message": "bad request"}})

        scene = req.get("scene") or "ap.diag"
        messages = req.get("messages") or []
        content = scripted_content(scene, messages)
        completion_tokens = max(24, len(content) // 2)

        return self._json(200, {
            "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.get("model", "mock-scene-model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": max(32, sum(len(str(m.get("content", ""))) for m in messages) // 3),
                "completion_tokens": completion_tokens,
                "total_tokens": max(64, sum(len(str(m.get("content", ""))) for m in messages) // 3) + completion_tokens,
            },
        })


if __name__ == "__main__":
    print("[mock-model] listening on :8090", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
