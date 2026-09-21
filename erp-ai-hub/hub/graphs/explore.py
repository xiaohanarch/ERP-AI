"""ap.explore 场景图：受限自主只读（第二档）。

与第一档（静态图、模型只填空）的根本差别：本图是**模型驱动的工具循环**——
模型自选下一步查什么、什么时候收尾（ReAct 式），不为每个问题画一张图。
安全不靠流程图，靠四条平台约束：

  1. 只读：场景工具白名单全部为只读工具（写工具不在 T2 scope 内，
     场景外请求直接被网关拒绝）；
  2. 步数上限：MAX_STEPS，超出强制用已有证据收尾；
  3. 步级最小授权：每步单独换 T2（scope=[当步工具]），比第一档更紧；
  4. 取证：应答尾部由平台附加工具清单与步数（不依赖模型自觉）。

这是「日常查询价值的主体」：问题形态开放（诊断/筛查/查字段/解释规则），
一条循环图全部承载，而不是每个问题一张静态图。
"""
from __future__ import annotations

import json

from hub import gw
from hub.graphs.agents import agent_for
from hub.graphs.state import GraphState, contract_messages, ctx_of
from hub.sdk import build_graph

AGENT = "ap-copilot"
SCENE = "ap.explore"
MAX_STEPS = 4
RESULT_HEAD = 1400          # 喂回模型的结果截断（上下文预算）
# 场景只读白名单（与 scenes.yaml ap.explore 一致；写工具不在其内）
READ_TOOLS = ["ap.invoice.checkValidation", "ap.invoice.getMatchDetail",
              "ap.invoice.listBlocked", "ap.invoice.getDerivedField",
              "ap.balance.query", "semantic.capability.discover",
              "semantic.operation.explain", "semantic.term.translate",
              "semantic.metadata.entities", "semantic.metadata.fields"]


def _messages(state: GraphState) -> list[dict]:
    """问题 + 已取得的工具结果（截断）+ 步数提示。"""
    msgs = contract_messages(SCENE, state["message"])
    for h in state.get("history") or []:
        msgs.append({"role": "user",
                     "content": f"[已执行] {h['tool']} 参数 {json.dumps(h['arguments'], ensure_ascii=False)} 返回：{h['result_head']}"})
    used = len(state.get("history") or [])
    msgs.append({"role": "user",
                 "content": f"[约束] 已用 {used}/{MAX_STEPS} 步。可用只读工具白名单："
                            f"{', '.join(READ_TOOLS)}。"
                            "输出下一步动作 JSON（call 从白名单选，或 final 收尾）。"})
    return msgs


def reason(state: GraphState) -> dict:
    """模型决定下一步：调哪个工具 / 是否收尾。判定权在模型，授权在平台。"""
    action = gw.ask_model(SCENE, _messages(state), ctx_of(state))
    used = len(state.get("history") or [])
    if (action.get("action") == "call" and action.get("tool")
            and used < MAX_STEPS):
        return {"next_tool": str(action["tool"]),
                "next_args": action.get("arguments") or {},
                "final_answer": ""}
    # final（或超步数）：收尾；answer 缺失时回退 reply（契约外输出的兜底）
    return {"next_tool": "",
            "final_answer": str(action.get("answer") or action.get("reply") or "")}


def route(state: GraphState) -> str:
    return "act" if state.get("next_tool") else "assemble"


def act(state: GraphState) -> dict:
    """执行当步工具：步级最小授权（T2 scope=[当步工具]），结果截断入历史。"""
    tool, args = state["next_tool"], state["next_args"]
    user, tenant = state["user"], state["tenant"]
    ok, err = True, None
    try:
        t2 = gw.exchange(agent_for(AGENT, tenant), SCENE, [tool], user, tenant)
        result = gw.mcp_call(t2, tool, args)
    except gw.GwToolError as e:
        result, ok, err = {"error": e.code, "message": e.message}, False, e.code
    except gw.GwError as e:
        # 模型选了白名单外/不可用工具：记错入历史，循环继续（模型可据此改选）
        result, ok, err = {"error": e.code, "message": e.message}, False, e.code
    history = list(state.get("history") or [])
    history.append({"tool": tool, "arguments": args,
                    "result_head": json.dumps(result, ensure_ascii=False)[:RESULT_HEAD]})
    calls = list(state.get("tool_calls") or [])
    call = {"tool": tool, "arguments": args, "ok": ok, "error": err}
    calls.append(call)
    return {"history": history, "tool_calls": calls, "last_call": call, "next_tool": ""}


def assemble(state: GraphState) -> dict:
    """收尾：模型结论 + 平台强制取证后缀（步数/工具清单——不依赖模型自觉）。"""
    calls = state.get("tool_calls") or []
    steps = len(calls)
    answer = str(state.get("final_answer") or "").strip()
    if not answer:
        # 超步数强制收尾：用已取得的证据组装（不允许无结论结束）
        findings = []
        for h in state.get("history") or []:
            if h.get("result_head"):
                findings.append(f"{h['tool']}：{h['result_head'][:200]}")
        reason_note = ("达到步数上限" if steps >= MAX_STEPS else "模型未给出结论文本")
        answer = (f"（{reason_note}，按已有证据强制收尾）"
                  + ("；".join(findings) if findings else "（未取得任何工具结果）"))
    evidence = "；".join(f"{c['tool']}{'✓' if c['ok'] else '✗' + str(c['error'] or '')}"
                        for c in calls) or "（零工具调用）"
    return {"answer": f"{answer}\n\n[取证] 受限自主只读：{steps}/{MAX_STEPS} 步，工具：{evidence}"}


def build():
    return build_graph(
        GraphState,
        nodes=[("reason", reason), ("act", act), ("assemble", assemble)],
        edges=[("START", "reason"), ("act", "reason"), ("assemble", "END")],
        conditional={"reason": (route, ["act", "assemble"])})
