"""Structured outputs used by the research agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchPlan(BaseModel):
    reasoning: str = Field(description="Two or three sentences: which documents are needed and why")
    code: str = Field(description="Python search plan for the sandbox. Must call emit() exactly once.")


class Finding(BaseModel):
    doc_id: str = Field(description="Id of the document this finding comes from")
    relevant: bool = Field(description="False if the document does not match the research question")
    exclusion_reason: str | None = Field(None, description="Why it is not relevant, when relevant is false")
    date: str = Field(description="Document date, YYYY-MM-DD")
    title: str
    cause_category: str = Field(description="Short snake_case label for the underlying root cause, e.g. "
                                            "'certificate_expiry' or 'database_lock_contention'")
    cause_summary: str = Field(description="One or two sentences in your own words: what actually caused it")
    impact: str = Field(description="Customer impact in a few words, with numbers if the document gives them")
    evidence_quote: str = Field(description="A short verbatim quote (max 25 words) from the document supporting the cause")
    earlier_action_still_open: bool = Field(description="True if the report says an action item from an earlier "
                                                        "incident had not been delivered and contributed")


class BatchFindings(BaseModel):
    findings: list[Finding]


class Cluster(BaseModel):
    name: str = Field(description="Short human-readable name of the shared root cause")
    description: str = Field(description="One sentence describing the mechanism")
    finding_indices: list[int] = Field(description="Indices of the findings that share this root cause")


class Clusters(BaseModel):
    clusters: list[Cluster]
