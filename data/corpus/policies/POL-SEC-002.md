---
doc_id: "POL-SEC-002"
title: "Access Control Policy"
department: "security"
document_type: "policy"
access_level: "internal"
created_date: "2025-06-01"
author: "E1007"
author_name: "Chamari Rathnayake"
tags: [security, access, iam]
---

# POL-SEC-002: Access Control Policy

## Scope
Covers access to applications, infrastructure, data stores and administrative consoles.

## Roles
Access is granted through roles, not individual permissions. Each role has a business owner who approves membership.

## Privileged access
- Production administrative access requires multi-factor authentication and a just-in-time elevation request.
- Elevation lasts at most four hours and is logged.
- Shared administrator accounts are prohibited.

## Reviews
Role owners recertify membership every quarter. Access not recertified is removed automatically after 14 days.

## Leavers
Access is revoked on the employee's last working day. Certificates, API keys and service credentials owned by a leaver are transferred to a named owner before departure.

## AI assistants
Internal AI assistants must enforce the same role-based access as the systems they query. An assistant must never return content that the requesting user could not open directly.
