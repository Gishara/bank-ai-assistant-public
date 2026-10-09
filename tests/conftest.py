from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

_tmp = tempfile.mkdtemp(prefix="bank-ai-tests-")
os.environ["STATE_DB"] = str(Path(_tmp) / "state.sqlite")
os.environ["PINECONE_API_KEY"] = ""
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["FAULTS"] = ""

import pytest  # noqa: E402

from core.auth import USERS  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def local_index():
    from core.config import get_settings
    from retrieval.ingest import build_local

    build_local(get_settings())


@pytest.fixture(autouse=True)
def clean_runtime():
    from api.ratelimit import limiter
    from core.resilience import breakers, faults
    from mcp_server.server import server
    from tools import mcp_client

    mcp_client.set_target(server)
    for name in list(faults.snapshot()):
        faults.set(name, False)
    for b in breakers.values():
        b.failures, b.opened_at = 0, None
    limiter.reset()
    yield
    mcp_client.set_target(None)


@pytest.fixture
def viewer():
    return USERS["viewer"][0]


@pytest.fixture
def analyst():
    return USERS["analyst"][0]


@pytest.fixture
def admin():
    return USERS["admin"][0]


@pytest.fixture
def fake_llm(monkeypatch):
    from fakes import FakeLLM, install

    return install(monkeypatch, FakeLLM())
