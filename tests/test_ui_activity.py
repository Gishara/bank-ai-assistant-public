from ui.activity import describe, parse_sse


def test_parse_sse_stream():
    lines = ["event: token", 'data: {"text": "Hi"}', "", "event: final", 'data: {"answer": "Hi"}', ""]
    assert list(parse_sse(lines)) == [("token", {"text": "Hi"}), ("final", {"answer": "Hi"})]


def test_describe_key_events():
    assert "Supervisor → **retrieve**" in describe("route", {"next": "retrieve", "requested": "retrieve", "reason": "r"})
    assert "not allowed" in describe("route", {"next": "respond", "requested": "admin", "reason": "r"})
    assert "keyword only" in describe("retrieval", {"ok": True, "mode": "keyword", "alpha": 0.6, "hits": []})
    assert "split" in describe("rlm_split", {"batch": "1", "tokens": 7000, "into": [4, 4], "depth": 0})
    assert "failed" in describe("validation", {"passed": False, "issues": ["x"], "attempt": 1})
    assert describe("node_end", {"node": "x"}) is None
