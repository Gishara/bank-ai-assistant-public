"""Validate an answer before it reaches the user.

Checks, in order:
  1. Every `[DOC-ID §Section]` citation names a document retrieved in this turn.
  2. Every `[tool:name]` citation names a tool that ran in this turn.
  3. A substantive answer built on evidence cites at least one source.
  4. No system-prompt canary or brand violation.
PII is masked regardless of the outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from security.brand_policy import brand_issues
from security.pii import mask_pii

DOC_CITATION_RE = re.compile(r"\[((?:INC|POL|ARC|RB|SPEC|MTG)-[A-Z0-9]+-\d{3,4})(?:\s*§\s*([^\]]+?))?\s*\]")
TOOL_CITATION_RE = re.compile(r"\[tool:([a-z_]+)\]")

# Embedded in the system prompt. If it ever appears in output, the prompt leaked.
CANARY = "cb-canary-7f3a91"

NO_ANSWER_MARKERS = re.compile(
    r"\b(I (couldn't|could not|can't|cannot|am unable to|was unable to)|no (relevant )?(documents?|information)|"
    r"not (able|authorized|permitted)|outside (my|the) scope|don't have access)\b", re.I)


@dataclass
class GuardResult:
    passed: bool
    answer: str
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cited_doc_ids: list[str] = field(default_factory=list)
    pii_masked: dict[str, int] = field(default_factory=dict)


def check_answer(answer: str, evidence_sections: dict[str, set[str]], tools_used: set[str]) -> GuardResult:
    issues: list[str] = []
    warnings: list[str] = []
    cited: list[str] = []

    for doc_id, section in DOC_CITATION_RE.findall(answer):
        if doc_id not in cited:
            cited.append(doc_id)
        if doc_id not in evidence_sections:
            issues.append(f"cites {doc_id}, which was not retrieved in this turn")
        elif section and evidence_sections[doc_id] and not any(
                section.strip().lower() in s.lower() or s.lower() in section.strip().lower()
                for s in evidence_sections[doc_id]):
            warnings.append(f"section '{section.strip()}' not found in retrieved parts of {doc_id}")

    tool_cites = TOOL_CITATION_RE.findall(answer)
    for name in tool_cites:
        if name not in tools_used:
            issues.append(f"cites tool {name}, which did not run in this turn")

    has_evidence = bool(evidence_sections or tools_used)
    substantive = len(answer.split()) > 40 and not NO_ANSWER_MARKERS.search(answer)
    if has_evidence and substantive and not cited and not tool_cites:
        issues.append("answer uses retrieved material but cites no sources")

    if CANARY in answer:
        issues.append("answer contains system prompt content")
    issues.extend(brand_issues(answer))

    masked, counts = mask_pii(answer)
    return GuardResult(passed=not issues, answer=masked, issues=issues, warnings=warnings,
                       cited_doc_ids=cited, pii_masked=counts)
