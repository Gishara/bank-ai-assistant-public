"""Roles, document access levels and tool permissions.

This module is the single place where authorization rules live. Nothing in
here is ever derived from model output: the role comes from the verified JWT,
and the rest is a static lookup.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMINISTRATOR = "administrator"


class AccessLevel(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


ROLE_ACCESS_LEVELS: dict[Role, tuple[AccessLevel, ...]] = {
    Role.VIEWER: (AccessLevel.PUBLIC, AccessLevel.INTERNAL),
    Role.ANALYST: (AccessLevel.PUBLIC, AccessLevel.INTERNAL, AccessLevel.CONFIDENTIAL),
    Role.ADMINISTRATOR: tuple(AccessLevel),
}

# Tool name -> roles allowed to use it. A tool missing from this table is
# denied to everyone, so adding a tool without deciding its scope fails closed.
TOOL_SCOPES: dict[str, frozenset[Role]] = {
    "knowledge_search": frozenset(Role),
    "python_analysis": frozenset({Role.ANALYST, Role.ADMINISTRATOR}),
    "employee_directory": frozenset({Role.ANALYST, Role.ADMINISTRATOR}),
    "service_catalog": frozenset({Role.ANALYST, Role.ADMINISTRATOR}),
    "incident_records": frozenset({Role.ANALYST, Role.ADMINISTRATOR}),
    "admin_view_audit_log": frozenset({Role.ADMINISTRATOR}),
    "admin_reindex_documents": frozenset({Role.ADMINISTRATOR}),
}

# Tools whose execution pauses for explicit human approval.
APPROVAL_REQUIRED: frozenset[str] = frozenset({"admin_reindex_documents"})

# Requests per bucket and refill rate (tokens per second), per role.
RATE_LIMITS: dict[Role, tuple[int, float]] = {
    Role.VIEWER: (10, 0.2),
    Role.ANALYST: (20, 0.5),
    Role.ADMINISTRATOR: (40, 1.0),
}


def allowed_access_levels(role: Role) -> list[str]:
    return [level.value for level in ROLE_ACCESS_LEVELS[Role(role)]]


def can_read(role: Role, access_level: str) -> bool:
    return access_level in allowed_access_levels(role)


def can_use_tool(role: Role, tool_name: str) -> bool:
    return Role(role) in TOOL_SCOPES.get(tool_name, frozenset())


def tools_for(role: Role) -> list[str]:
    return [name for name in TOOL_SCOPES if can_use_tool(role, name)]
