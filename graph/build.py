"""Assemble the main agent graph.

    START -> prepare -> supervisor --route--> retrieve | research | tools | admin --> supervisor
                                     \\-> respond -> output_guard --fail once--> respond
                                                                  \\-> memory_write -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph import nodes
from graph.state import AgentState

WORKERS = ("retrieve", "research", "tools", "admin")


def build_graph(checkpointer=None, store=None):
    g = StateGraph(AgentState)
    g.add_node("prepare", nodes.prepare)
    g.add_node("supervisor", nodes.supervisor)
    g.add_node("retrieve", nodes.retrieve)
    g.add_node("research", nodes.research)
    g.add_node("tools", nodes.tools)
    g.add_node("admin", nodes.admin)
    g.add_node("respond", nodes.respond)
    g.add_node("output_guard", nodes.output_guard)
    g.add_node("memory_write", nodes.memory_write)

    g.add_edge(START, "prepare")
    g.add_edge("prepare", "supervisor")
    g.add_conditional_edges("supervisor", nodes.route, {w: w for w in WORKERS} | {"respond": "respond"})
    for w in WORKERS:
        g.add_edge(w, "supervisor")
    g.add_edge("respond", "output_guard")
    g.add_conditional_edges("output_guard", nodes.after_guard, {"respond": "respond", "memory_write": "memory_write"})
    g.add_edge("memory_write", END)
    return g.compile(checkpointer=checkpointer, store=store, name="bank_assistant")
