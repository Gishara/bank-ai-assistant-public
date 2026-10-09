from core import audit
from core.resilience import faults
from tools.gateway import ToolGateway


def test_model_only_sees_tools_for_its_role(viewer, analyst, admin):
    assert [t.name for t in ToolGateway(viewer).bindable_tools()] == ["knowledge_search"]
    analyst_tools = {t.name for t in ToolGateway(analyst).bindable_tools()}
    assert "incident_records" in analyst_tools and not any(n.startswith("admin_") for n in analyst_tools)
    # Admin tools are never bound to the model; they go through the admin node.
    assert not any(t.name.startswith("admin_") for t in ToolGateway(admin).bindable_tools())


async def test_execution_rechecks_role_even_if_model_names_the_tool(viewer):
    out = await ToolGateway(viewer).execute("employee_directory", {"query": "Malith"})
    assert not out.ok and out.error_kind == "denied"
    assert audit.recent(1)[0]["outcome"] == "denied"


async def test_admin_tool_requires_approval(admin):
    out = await ToolGateway(admin).execute("admin_reindex_documents", {"scope": "local"})
    assert not out.ok and out.error_kind == "needs_approval"


async def test_arguments_are_validated(analyst):
    out = await ToolGateway(analyst).execute("knowledge_search", {"query": "x", "filters": {"access_level": "restricted"}})
    assert not out.ok and out.error_kind == "invalid_args"


async def test_mcp_lookup_and_numbers(analyst):
    svc = await ToolGateway(analyst).execute("service_catalog", {"service_id": "hsm-gateway"})
    assert svc.ok and svc.data["service"]["owner_name"] == "Malith Herath"
    sev1 = await ToolGateway(analyst).execute("incident_records", {"severity": "SEV1", "date_from": "2026-01-01"})
    assert sev1.ok and sev1.data["count"] == 3 and sev1.data["total_failed_transactions"] == 76200


async def test_incident_records_follow_document_access(analyst, admin):
    from core.auth import USERS

    viewer = USERS["viewer"][0]
    # Viewers cannot call MCP at all; analysts see the confidential phishing record.
    rows = await ToolGateway(analyst).execute("incident_records", {"date_from": "2026-06-01", "date_to": "2026-06-01"})
    assert [r["incident_id"] for r in rows.data["incidents"]] == ["INC-2026-0601"]
    assert not (await ToolGateway(viewer).execute("incident_records", {})).ok


async def test_mcp_outage_degrades_cleanly(analyst):
    faults.set("mcp", True)
    out = await ToolGateway(analyst).execute("employee_directory", {"query": "x"})
    assert not out.ok and out.error_kind == "unavailable"


async def test_retrieved_injection_is_stripped(viewer):
    out = await ToolGateway(viewer).execute("knowledge_search", {"query": "Digital Channels weekly sync pasted vendor chat"})
    assert out.ok and out.sanitized
    assert not any("maintenance mode" in h["text"] for h in out.data["hits"])


async def test_python_analysis_over_records(analyst):
    out = await ToolGateway(analyst).execute("python_analysis", {
        "code": "rows = [i for i in incidents if i['severity'] == 'SEV1' and i['date'] >= '2026-01-01']\nresult = sum(i['failed_transactions'] for i in rows)"})
    assert out.ok and out.data["result"] == 76200
