from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

THREAD_ID = r"^[A-Za-z0-9_-]{1,64}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ChatRequest(Strict):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(pattern=THREAD_ID)


class ResumeRequest(Strict):
    thread_id: str = Field(pattern=THREAD_ID)
    approved: bool
    comment: str | None = Field(None, max_length=500)


class FeedbackRequest(Strict):
    run_id: UUID
    score: Literal[0, 1]
    comment: str | None = Field(None, max_length=1000)


class FaultRequest(Strict):
    name: Literal["llm", "pinecone", "mcp"]
    enabled: bool
