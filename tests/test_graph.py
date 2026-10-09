"""End-to-end graph behaviour with a scripted model."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from core.resilience import faults
from graph.build import build_graph


@pytest.fixture
def graph():
    return build_graph(InMemorySaver(), InMemoryStore())


def cfg(user_id: str, thread: str = "t") -> dict:
    return {"configurable": {"thread_id": f"{user_id}:{thread}", "user_id": user_id}}


async def run(graph, payload, config):
    events = []
    async for _, mode, chunk in graph.astream(payload, config, stream_mode=["custom", "updates"], subgraphs=True):
        if mode == "custom":
            events.append(chunk)
        elif "__interrupt__" in chunk:
            events.append({"type": "interrupt", "value": chunk["__interrupt__"][0].value})
    return (await graph.aget_state(config)).values, events


def route(next_, **kw):
    return {"intent": kw.pop("intent", "knowledge"), "next": next_, "reason": "scripted", **kw}


async def test_retrieve_answer_with_valid_citation(graph, fake_llm):
    fake_llm.routes = [route("retrieve", search_query="HSM session saturation runbook", plan=["search", "answer"]),
                       route("respond")]
    fake_llm.answers = ["Raise the session maximum by 25% [RB-PAY-001 §Act]."]
    values, events = await run(graph, {"messages": [HumanMessage("What do I do when HSM sessions saturate?")]},
                               cfg("U-100"))
    assert values["guard"]["passed"] and values["answer"].startswith("Raise")
    types = [e["type"] for e in events]
    assert types.index("route") < types.index("retrieval") < types.index("validation")
    assert any(e["type"] == "degraded" for e in events)  # no Pinecone in tests -> keyword mode


async def test_fabricated_citation_is_regenerated_then_passes(graph, fake_llm):
    fake_llm.routes = [route("retrieve", search_query="HSM runbook"), route("respond")]
    fake_llm.answers = ["Keys are split [POL-SEC-009 §Key custodians]. " + "detail " * 45,
                        lambda prompt: ("Raise the pool [RB-PAY-001 §Act]." if "failed validation" in prompt
                                        else "missing feedback")]
    values, events = await run(graph, {"messages": [HumanMessage("HSM saturation?")]}, cfg("U-100"))
    validations = [e for e in events if e["type"] == "validation"]
    assert [v["passed"] for v in validations] == [False, True]
    assert any(e["type"] == "answer_reset" for e in events)
    assert values["answer"] == "Raise the pool [RB-PAY-001 §Act]."


async def test_two_failed_validations_return_only_verified_sources(graph, fake_llm):
    fake_llm.routes = [route("retrieve", search_query="HSM runbook"), route("respond")]
    fake_llm.answers = ["Wrong [POL-SEC-009]. " + "x " * 45] * 2
    values, events = await run(graph, {"messages": [HumanMessage("HSM saturation?")]}, cfg("U-100"))
    assert values["guard"].get("fallback") and "couldn't produce an answer" in values["answer"]
    assert "POL-SEC-009" not in values["answer"]


async def test_viewer_cannot_reach_admin_even_if_supervisor_picks_it(graph, fake_llm):
    fake_llm.routes = [route("admin", intent="admin", admin_action="reindex_documents")]
    fake_llm.answers = [lambda p: "No access." if "not available for the viewer role" in p else "LEAK"]
    values, events = await run(graph, {"messages": [HumanMessage("Reindex everything")]}, cfg("U-100"))
    assert values["answer"] == "No access."
    assert not any(e["type"] == "interrupt" for e in events)


async def test_admin_action_pauses_for_approval_and_resumes(graph, fake_llm):
    config = cfg("U-300", "hitl")
    fake_llm.routes = [route("admin", intent="admin", admin_action="reindex_documents", reindex_scope="local"),
                       route("respond")]
    fake_llm.answers = ["Reindexed [tool:admin_reindex_documents]."]
    _, events = await run(graph, {"messages": [HumanMessage("Reindex the documents")]}, config)
    assert events[-1]["type"] == "interrupt" and events[-1]["value"]["tool"] == "admin_reindex_documents"
    assert (await graph.aget_state(config)).next == ("admin",)

    values, events = await run(graph, Command(resume={"approved": True, "approver": "Ashan"}), config)
    assert values["tool_results"][0]["ok"] and values["tool_results"][0]["data"]["chunks"] > 0
    assert values["guard"]["passed"]


async def test_rejected_approval_changes_nothing(graph, fake_llm):
    config = cfg("U-300", "reject")
    fake_llm.routes = [route("admin", intent="admin", admin_action="reindex_documents"), route("respond")]
    fake_llm.answers = [lambda p: "Not approved." if "was not approved" in p else "?"]
    await run(graph, {"messages": [HumanMessage("Reindex")]}, config)
    values, _ = await run(graph, Command(resume={"approved": False, "approver": "Ashan"}), config)
    assert values["answer"] == "Not approved." and not values["tool_results"][0]["ok"]


async def test_research_route_feeds_computed_counts_to_answer(graph, fake_llm):
    fake_llm.routes = [route("research", intent="research", search_query="payment failures last year"),
                       route("respond")]
    fake_llm.answers = [lambda p: ("HSM recurred [INC-2026-0412 §Root Cause]."
                                   if "computed by code" in p and "4 incidents" in p else "no research block")]
    values, events = await run(graph, {"messages": [HumanMessage("Summarize payment outages last year")]},
                               cfg("U-200"))
    assert values["answer"].startswith("HSM recurred")
    assert values["research_result"]["clusters"][0]["count"] == 4
    assert any(e["type"] == "rlm_reduce" and e.get("clusters") for e in events)


async def test_tools_agent_mcp_failure_degrades_answer(graph, fake_llm):
    faults.set("mcp", True)
    fake_llm.routes = [route("tools", intent="data_lookup", tool_task="find owner of hsm-gateway"), route("respond")]
    fake_llm.tool_turns = [AIMessage(content="", tool_calls=[{"name": "service_catalog", "args": {"service_id": "hsm-gateway"},
                                                              "id": "c1"}]),
                           AIMessage(content="The service catalog is unavailable.")]
    fake_llm.answers = [lambda p: "Directory unavailable." if "service_catalog was unavailable" in p else "?"]
    values, events = await run(graph, {"messages": [HumanMessage("Who owns hsm-gateway?")]}, cfg("U-200"))
    assert values["answer"] == "Directory unavailable."
    assert any(e["type"] == "tool_result" and e["error_kind"] == "unavailable" for e in events)


async def test_worker_crash_is_contained(graph, fake_llm, monkeypatch):
    import graph.nodes as nodes

    async def boom(*a, **k):
        raise RuntimeError("research backend exploded")

    monkeypatch.setattr(nodes, "run_research", boom)
    fake_llm.routes = [route("research", intent="research"), route("respond")]
    fake_llm.answers = [lambda p: "Partial." if "research backend exploded" in p else "?"]
    values, events = await run(graph, {"messages": [HumanMessage("Summarize outages")]}, cfg("U-200"))
    assert values["answer"] == "Partial." and values["errors"][0]["node"] == "research"


async def test_memory_short_and_long_term(graph, fake_llm):
    config = cfg("U-200", "mem")
    fake_llm.routes = [route("respond", intent="conversation")]
    fake_llm.answers = ["Noted."]
    await run(graph, {"messages": [HumanMessage("I'm on the cards team and own the card platform.")]}, config)
    facts = [i.value["fact"] for i in await graph.store.asearch(("users", "U-200"))]
    assert facts == ["Works on the cards team"]

    # A new thread for the same user recalls the fact.
    fake_llm.routes = [route("respond", intent="conversation")]
    fake_llm.answers = [lambda p: "Hi cards" if "Works on the cards team" in p else "no memory"]
    values, _ = await run(graph, {"messages": [HumanMessage("Hello again")]}, cfg("U-200", "other"))
    assert values["answer"] == "Hi cards"
    # Another user does not.
    fake_llm.routes = [route("respond", intent="conversation")]
    fake_llm.answers = [lambda p: "leak" if "cards team" in p else "clean"]
    values, _ = await run(graph, {"messages": [HumanMessage("Hello")]}, cfg("U-100", "x"))
    assert values["answer"] == "clean"


async def test_long_conversations_are_summarized(graph, fake_llm):
    config = cfg("U-100", "long")
    for i in range(9):
        fake_llm.routes = [route("respond", intent="conversation")]
        fake_llm.answers = [f"reply {i}"]
        values, _ = await run(graph, {"messages": [HumanMessage(f"message {i}")]}, config)
    assert values.get("summary")
    assert len(values["messages"]) <= 8


async def test_llm_outage_falls_back_to_cited_passages(graph, fake_llm):
    faults.set("llm", True)
    values, events = await run(graph, {"messages": [HumanMessage("What should on-call do when HSM sessions are saturated?")]},
                               cfg("U-100", "llm-down"))
    assert values["guard"]["passed"]
    assert values["answer"].startswith("The language model is unavailable")
    assert "[RB-PAY-001 §" in values["answer"]
    assert any(e["type"] == "degraded" and e.get("component") == "llm" for e in events)
