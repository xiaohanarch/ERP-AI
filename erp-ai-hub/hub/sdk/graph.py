"""LangGraph 薄封装 —— hub 内唯一允许 import langgraph 的模块。

封装内容：
  - get_saver()    PostgresSaver 检查点（挂起持久化；approvalId↔thread 映射由 hub.db 承担）
  - build_graph()  节点/边/条件边的统一装配
  - run_graph()    同步执行，返回 (最终 state, interrupt 载荷 | None)
  - resume_graph() 审批唤醒（Command(resume=...)）
  - stream_graph() 按节点更新流式执行（SSE 事件源）
graphs 层只 import hub.sdk，不直接接触 langgraph API。
"""
from __future__ import annotations

from typing import Any, Callable, Iterator

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from langgraph.types import interrupt as _langgraph_interrupt

from hub import config

_saver_cm = None
_saver: PostgresSaver | None = None


def get_saver() -> PostgresSaver:
    global _saver_cm, _saver
    if _saver is None:
        _saver_cm = PostgresSaver.from_conn_string(config.settings.database_url)
        _saver = _saver_cm.__enter__()
        _saver.setup()
    return _saver


def build_graph(state_schema: Any, nodes: list[tuple[str, Callable]],
                edges: list[tuple[str, str]],
                conditional: dict[str, tuple[Callable, list[str]]] | None = None):
    """装配图。edges 用 (START, a) / (a, b) / (a, END) 字符串；conditional 为路由表。"""
    graph = StateGraph(state_schema)
    _node = {"START": START, "END": END}
    for name, fn in nodes:
        graph.add_node(name, fn)
    for a, b in edges:
        graph.add_edge(_node.get(a, a), _node.get(b, b))
    for src, (router, targets) in (conditional or {}).items():
        graph.add_conditional_edges(src, router, targets)
    return graph.compile(checkpointer=get_saver())


def interrupt(payload: Any) -> Any:
    """节点内审批断点：首次执行挂起并抛出载荷；恢复时返回唤醒值。"""
    return _langgraph_interrupt(payload)


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def run_graph(graph, state_in: dict, thread_id: str) -> tuple[dict, Any]:
    """同步执行到完成或挂起。返回 (最终 state.values, interrupt 载荷或 None)。"""
    graph.invoke(state_in, _thread_config(thread_id))
    snapshot = graph.get_state(_thread_config(thread_id))
    payload = None
    if snapshot.next:
        for task in getattr(snapshot, "tasks", ()):
            for intr in getattr(task, "interrupts", ()) or ():
                payload = intr.value
                break
            if payload is not None:
                break
    return dict(snapshot.values or {}), payload


def resume_graph(graph, thread_id: str, resume_value: dict) -> dict:
    """审批唤醒：恢复挂起的节点（interrupt 处返回 resume_value）。"""
    result = graph.invoke(Command(resume=resume_value), _thread_config(thread_id))
    return dict(result or {})


def stream_graph(graph, state_in: dict, thread_id: str) -> Iterator[tuple[str, Any]]:
    """按节点更新流式执行。yield (节点名, 增量 state) 或 ("__interrupt__", 载荷)。"""
    for update in graph.stream(state_in, _thread_config(thread_id), stream_mode="updates"):
        for node, delta in update.items():
            if node == "__interrupt__":
                for intr in delta:
                    yield "__interrupt__", intr.value
            else:
                yield node, (delta or {})


def state_of(graph, thread_id: str) -> dict:
    snapshot = graph.get_state(_thread_config(thread_id))
    return dict(snapshot.values or {})


def is_suspended(graph, thread_id: str) -> bool:
    snapshot = graph.get_state(_thread_config(thread_id))
    return bool(snapshot.next)
