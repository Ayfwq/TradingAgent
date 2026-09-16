"""交错完成测试：如果一个并行分支较晚完成（跨越多个波次），LangGraph 1.2
的扇入会等待它，还是连接节点提前触发后再次触发，从而破坏下游循环？"""

import sys
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class S(TypedDict):
    k0: str
    k1: str
    k2: str
    k3: str
    history: str
    count: int


def make_worker(key):
    def worker(state):
        return {key: f"[{key}]"}
    return worker


def slow_worker(key, delay):
    def worker(state):
        time.sleep(delay)
        return {key: f"[{key}-slow]"}
    return worker


def join_node(state):
    return {"history": state["history"] + "[X]", "count": state["count"] + 1}


def loop_node(state):
    return {"history": state["history"] + "[Y]"}


def route_x(state):
    return "END" if state["count"] >= 2 else "Y"


def route_y(state):
    return "X"


def build(stagger_worker=1):
    """w0..w2 -> c0..c2 -> X（同一深度层）
    w3 -> w3b -> c3 -> X（c3 深一层）
    X<->Y 循环。X 是否会在 c3 到达前触发（跨层连接遗漏）？"""
    g = StateGraph(S)
    for i in range(3):
        g.add_node(f"w{i}", make_worker(f"k{i}"))
        g.add_node(f"c{i}", make_worker(f"k{i}"))
        g.add_edge(START, f"w{i}")
        g.add_edge(f"w{i}", f"c{i}")
        g.add_edge(f"c{i}", "X")
    # 更深的分支：w3 -> w3b -> c3
    g.add_node("w3", make_worker("k3"))
    g.add_node("w3b", make_worker("k3"))
    g.add_node("c3", make_worker("k3"))
    g.add_edge(START, "w3")
    g.add_edge("w3", "w3b")
    g.add_edge("w3b", "c3")
    g.add_edge("c3", "X")
    g.add_node("X", join_node)
    g.add_node("Y", loop_node)
    g.add_conditional_edges("X", route_x, {"Y": "Y", "END": END})
    g.add_conditional_edges("Y", route_y, {"X": "X"})
    return g.compile()


if __name__ == "__main__":
    graph = build()
    t0 = time.monotonic()
    try:
        for chunk in graph.stream({"k0": "", "k1": "", "k2": "", "k3": "",
                                   "history": "", "count": 0},
                                  stream_mode="updates"):
            print(chunk)
        print("成功")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"失败：{type(exc).__name__}：{str(exc)[:200]}")
        sys.exit(1)
