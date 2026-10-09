"""Application settings, read from environment variables or a .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Models
    llm_large: str = "anthropic:claude-sonnet-5-5"
    llm_small: str = "anthropic:claude-haiku-5-5"
    llm_fallback: str = ""
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index: str = "bank-kb"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    embed_model: str = "multilingual-e5-large"
    embed_dimension: int = 1024
    rerank_model: str = "bge-reranker-v2-m3"

    # Retrieval
    hybrid_alpha: float = 0.6
    hybrid_alpha_ids: float = 0.3
    retrieve_top_k: int = 20
    rerank_top_n: int = 6

    # Agent limits
    max_hops: int = 4
    tool_timeout_s: float = 8.0
    rlm_batch_size: int = 6
    rlm_batch_token_limit: int = 6000
    rlm_max_depth: int = 2
    rlm_concurrency: int = 4
    summarize_after_messages: int = 16

    # API
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 480
    state_db: Path = ROOT / "data" / "state" / "assistant.sqlite"
    mcp_server_url: str = "http://localhost:8001/mcp"
    faults: str = Field(default="", description="comma-separated: llm,pinecone,mcp")

    # Paths
    corpus_dir: Path = ROOT / "data" / "corpus"
    index_dir: Path = ROOT / "data" / "index"
    mcp_data_dir: Path = ROOT / "mcp_server" / "data"

    @property
    def pinecone_enabled(self) -> bool:
        return bool(self.pinecone_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
