"""Research agent mechanics against the planted ground truth.

The analyzer stub labels documents with their true cause, so these tests check
everything around the model: the plan runs in the sandbox, batches fan out,
oversized batches split and recurse, reduce runs once, and the counts match.
"""

import json

from core.config import get_settings
from rlm.graph import rlm_graph, run_research

QUESTION = "Summarize all outage reports related to payment failures during the last year and identify recurring root causes."
GT = json.load(open("data/ground_truth.json"))


async def _run(user_id="U-200"):
    events, reduce_runs = [], 0
    result = None
    async for _, mode, chunk in rlm_graph.astream({"question": QUESTION, "user_id": user_id, "today": "2026-10-09"},
                                                   stream_mode=["custom", "updates"], subgraphs=True):
        if mode == "custom":
            events.append(chunk)
        elif mode == "updates" and (chunk.get("reduce") or {}).get("result"):
            reduce_runs += 1
            result = chunk["reduce"]["result"]
    return result, events, reduce_runs


async def test_research_matches_ground_truth(fake_llm):
    result, events, reduce_runs = await _run()
    assert reduce_runs == 1
    got = {c["count"]: set() for c in result["clusters"]}
    for c in result["clusters"]:
        got[c["count"]].add(frozenset(c["doc_ids"]))
    expected = {}
    for rc in GT["root_causes"]:
        expected.setdefault(rc["count"], set()).add(frozenset(rc["incident_ids"]))
    assert got == expected
    assert sorted(f["doc_id"] for f in result["findings"]) == GT["expected_incident_ids"]
    excluded = {e["doc_id"] for e in result["excluded"]}
    assert {"INC-2026-0109", "INC-2026-0902"} <= excluded
    assert {e["type"] for e in events} >= {"rlm_catalog", "rlm_plan", "rlm_sandbox", "rlm_batches", "rlm_reduce"}


async def test_oversized_batches_split_and_reduce_once(fake_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "rlm_batch_token_limit", 2500)
    result, events, reduce_runs = await _run()
    assert any(e["type"] == "rlm_split" for e in events)
    assert result["max_depth"] >= 1 and reduce_runs == 1
    assert sorted(f["doc_id"] for f in result["findings"]) == GT["expected_incident_ids"]


async def test_bad_plan_is_retried_with_its_error(fake_llm):
    fake_llm.plans = ["import os", "emit([], task='x')",
                      "hits=[d for d in catalog if d.document_type=='incident']\nemit(chunk(hits, 8), task='t')"]
    result, events, _ = await _run()
    sandbox_events = [e for e in events if e["type"] == "rlm_sandbox"]
    assert not sandbox_events[0]["ok"]
    planner_prompts = [t for name, t in fake_llm.calls if name == "SearchPlan"]
    assert "Import is not allowed" in planner_prompts[1]
    # Two failures -> keyword-ranked fallback plan, still producing findings.
    assert any(e.get("fallback") for e in events if e["type"] == "rlm_batches")
    assert result["findings"]


async def test_viewer_research_never_includes_confidential_docs(fake_llm):
    fake_llm.plans = ["emit(chunk(catalog, 10), task='t')"]
    result, events, _ = await _run(user_id="U-100")
    analyzed = {e["doc_ids"][i] for e in events if e["type"] == "rlm_batch_start" for i in range(len(e["doc_ids"]))}
    assert analyzed and not ({"POL-RSK-004", "POL-SEC-009", "ARC-RSK-001", "INC-2026-0601"} & analyzed)


async def test_failed_batch_degrades_instead_of_failing(fake_llm):
    fake_llm.fail_structured.add("BatchFindings")
    result = await run_research(QUESTION, "U-200")
    assert result["findings"] == [] and any("not analyzed" in n for n in result["notes"])
