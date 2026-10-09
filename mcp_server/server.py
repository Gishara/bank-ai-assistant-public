"""Bank operations MCP server: employee directory, service catalog, incident records.

    python -m mcp_server.server            # streamable HTTP on :8001/mcp

The data comes from mcp_server/data/*.json, generated with the corpus, so ids
line up with the documents. Authorization is enforced by the assistant's tool
gateway before any call reaches this server.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

DATA = Path(__file__).parent / "data"


def _load(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


EMPLOYEES = _load("employees")
SERVICES = _load("services")
INCIDENTS = _load("incidents")
EMP_BY_ID = {e["id"]: e for e in EMPLOYEES}

server = MCPServer(
    name="bank-ops",
    instructions="Read-only lookups over the bank's employee directory, service catalog and incident records.",
)


def _with_owner(service: dict) -> dict:
    owner = EMP_BY_ID.get(service["owner_id"], {})
    return service | {"owner_name": owner.get("name"), "owner_on_call": owner.get("on_call")}


@server.tool(description="Find employees by name, id, team, department or job title (case-insensitive substring).")
def lookup_employee(query: str) -> dict[str, Any]:
    q = query.lower().strip()
    hits = [e for e in EMPLOYEES
            if q in e["id"].lower() or q in e["name"].lower() or q in e["team"].lower()
            or q in e["department"].lower() or q in e["title"].lower()]
    return {"query": query, "count": len(hits), "employees": hits[:20]}


@server.tool(description="Get one service by id, including owner, tier, dependencies and runbooks.")
def get_service(service_id: str) -> dict[str, Any]:
    for s in SERVICES:
        if s["id"] == service_id:
            dependents = [d["id"] for d in SERVICES if service_id in d["depends_on"]]
            return {"found": True, "service": _with_owner(s) | {"dependents": dependents}}
    return {"found": False, "service_id": service_id, "known_ids": [s["id"] for s in SERVICES]}


@server.tool(description="Search services by name, team or description (case-insensitive substring).")
def search_services(query: str) -> dict[str, Any]:
    q = query.lower().strip()
    hits = [_with_owner(s) for s in SERVICES
            if q in s["id"] or q in s["name"].lower() or q in s["owner_team"].lower() or q in s["description"].lower()]
    return {"query": query, "count": len(hits), "services": hits}


@server.tool(description=("List incident records. Optional filters: severity (SEV1-SEV4), date_from and date_to "
                          "(YYYY-MM-DD, inclusive), service_id. Results are sorted by date."))
def list_incidents(severity: str | None = None, date_from: str | None = None, date_to: str | None = None,
                   service_id: str | None = None) -> dict[str, Any]:
    rows = INCIDENTS
    if severity:
        rows = [r for r in rows if r["severity"] == severity.upper()]
    if date_from:
        rows = [r for r in rows if r["date"] >= date_from]
    if date_to:
        rows = [r for r in rows if r["date"] <= date_to]
    if service_id:
        rows = [r for r in rows if service_id in r["services"]]
    return {
        "count": len(rows),
        "total_failed_transactions": sum(r["failed_transactions"] for r in rows),
        "total_customers_affected": sum(r["customers_affected"] for r in rows),
        "incidents": rows,
    }


@server.tool(description="Get one incident record by id, e.g. INC-2026-0412.")
def get_incident(incident_id: str) -> dict[str, Any]:
    for r in INCIDENTS:
        if r["incident_id"] == incident_id.upper():
            return {"found": True, "incident": r}
    return {"found": False, "incident_id": incident_id}


def main() -> None:
    import asyncio

    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8001"))
    asyncio.run(server.run_streamable_http_async(host=host, port=port, stateless_http=True, json_response=True))


if __name__ == "__main__":
    main()
