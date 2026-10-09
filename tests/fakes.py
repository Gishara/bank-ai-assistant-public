"""Scripted stand-ins for the LLM, so graph tests run without API keys.

`FakeLLM` replaces core.llm.chat / core.llm.structured. Structured calls are
answered by schema type; chat calls by a queue of scripted AIMessages or a
callable. The research analyzer stub labels incidents with their planted
ground-truth cause, so tests check the research pipeline's mechanics (plan,
sandbox, fan-out, recursion, reduce, counting), not a model's judgment.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from corpus.incidents import INCIDENTS  # noqa: E402

GROUND = {i["id"]: i for i in INCIDENTS}
CAUSE_NAMES = {
    "hsm_pool_exhaustion": "HSM capacity exhaustion",
    "certificate_lifecycle": "Certificate lifecycle",
    "eod_batch_lock_contention": "Settlement batch lock contention",
    "fraud_api_no_fallback": "Fraud API without fallback",
}

DEFAULT_PLAN = '''hits = [d for d in catalog
        if d.document_type == "incident" and d.created_date >= today - timedelta(days=366)]
emit(chunk(sorted(hits, key=lambda d: d.created_date), 8),
     task="Extract the root cause, impact and whether an earlier action was still open.")
'''


def _text(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        return "\n".join(_text(m) for m in prompt)
    content = getattr(prompt, "content", prompt)
    return content if isinstance(content, str) else str(content)


class FakeLLM:
    def __init__(self) -> None:
        self.plans: list[str] = [DEFAULT_PLAN]
        self.routes: list[dict] = []
        self.answers: list[str | Callable[[str], str]] = []
        self.tool_turns: list[AIMessage] = []
        self.calls: list[tuple[str, str]] = []
        self.fail_structured: set[str] = set()

    # ------------------------------------------------------------ structured
    def structured(self, schema, size="large"):
        name = schema.__name__

        async def run(prompt):
            text = _text(prompt)
            self.calls.append((name, text))
            if name in self.fail_structured:
                raise RuntimeError(f"scripted failure for {name}")
            return self._answer(schema, text)

        return RunnableLambda(lambda p: None, afunc=run, name=f"fake_{name}")

    def _answer(self, schema, text: str):
        name = schema.__name__
        if name == "SearchPlan":
            code = self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
            return schema(reasoning="Payment incidents in the last year.", code=code)
        if name == "RoutingDecision":
            route = self.routes.pop(0) if self.routes else {"intent": "conversation", "next": "respond",
                                                             "reason": "default", "plan": []}
            return schema(**route)
        if name == "BatchFindings":
            return schema(findings=[self._finding(d) for d in re.findall(r'doc_id="([^"]+)"', text)])
        if name == "Clusters":
            return self._clusters(schema, text)
        if name == "MemoryFacts":
            facts = ["Works on the cards team"] if "cards team" in text.lower() else []
            return schema(facts=facts)
        if name == "ConversationSummary":
            return schema(summary="Earlier the user asked about payment incidents.")
        if name == "InjectionVerdict":
            return schema(is_injection="ignore" in text.lower(), reason="scripted")
        raise AssertionError(f"FakeLLM has no answer for {name}")

    @staticmethod
    def _finding(doc_id: str) -> dict:
        inc = GROUND.get(doc_id)
        if inc is None:
            return dict(doc_id=doc_id, relevant=False, exclusion_reason="not an incident report", date="2026-01-01",
                        title=doc_id, cause_category="n_a", cause_summary="n/a", impact="n/a",
                        evidence_quote="n/a", earlier_action_still_open=False)
        relevant = inc["payment"] and inc["cause"] in CAUSE_NAMES | {"change_management": 1, "dns_change": 1}
        return dict(doc_id=doc_id, relevant=relevant,
                    exclusion_reason=None if relevant else "not a payment failure",
                    date=inc["date"], title=inc["title"], cause_category=inc["cause"],
                    cause_summary=inc["root_cause"][:160], impact=inc["summary"][:80],
                    evidence_quote=" ".join(inc["root_cause"].split()[:12]),
                    earlier_action_still_open="still" in inc["root_cause"].lower()
                    or any("carried over" in a[1] for a in inc["actions"]))

    @staticmethod
    def _clusters(schema, text: str):
        groups: dict[str, list[int]] = {}
        for idx, cause in re.findall(r"^\[(\d+)\] \S+ \(\S+\) (\w+):", text, re.M):
            groups.setdefault(cause, []).append(int(idx))
        return schema(clusters=[{"name": CAUSE_NAMES.get(c, c), "description": c, "finding_indices": ids}
                                for c, ids in groups.items()])

    # ------------------------------------------------------------------ chat
    def next_answer(self, text: str) -> str:
        self.calls.append(("chat", text))
        answer = self.answers.pop(0) if self.answers else "I couldn't find that in the documents."
        return answer(text) if callable(answer) else answer

    def chat(self, size="large", *, tools=None, tags=None):
        if tools:
            async def run(messages):
                self.calls.append(("tools_chat", _text(messages)))
                return self.tool_turns.pop(0) if self.tool_turns else AIMessage(content="Done.")
            return RunnableLambda(lambda m: None, afunc=run, name="fake_tool_chat")
        # A real chat model, so LangGraph's "messages" stream sees token chunks.
        return ScriptedChatModel(script=self).with_config(tags=tags or [])


class ScriptedChatModel(BaseChatModel):
    script: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        text = self.script.next_answer(_text(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        text = self.script.next_answer(_text(messages))
        for i, word in enumerate(text.split(" ")):
            piece = word if i == 0 else " " + word
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                await run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk


def install(monkeypatch, fake: FakeLLM) -> FakeLLM:
    import core.llm
    import graph.nodes as nodes
    import rlm.graph as rlm_graph
    import security.injection as injection

    for mod in (core.llm, nodes, rlm_graph):
        if hasattr(mod, "structured"):
            monkeypatch.setattr(mod, "structured", fake.structured)
        if hasattr(mod, "chat"):
            monkeypatch.setattr(mod, "chat", fake.chat)
    monkeypatch.setattr(injection, "classify", None, raising=False)
    return fake
