---
doc_id: "POL-OPS-001"
title: "Incident Management Policy"
department: "platform"
document_type: "policy"
access_level: "internal"
created_date: "2025-09-01"
author: "E1011"
author_name: "Amaya de Silva"
tags: [operations, incident, policy, severity]
---

# POL-OPS-001: Incident Management Policy

## Severity levels
| Severity | Definition | Response |
|---|---|---|
| SEV1 | Tier 1 customer-facing service unavailable or more than 25% of transactions failing for over 15 minutes | Incident commander within 10 minutes; CTO and communications notified |
| SEV2 | Tier 1 service degraded, or a tier 2 service unavailable | Incident commander within 15 minutes |
| SEV3 | Limited customer impact or a workaround exists | Owning team handles in business hours |
| SEV4 | Internal impact only | Ticket |

## Roles
The incident commander coordinates and decides; they do not debug. The Major Incident Manager on rota acts as commander for SEV1 and SEV2.

## Post-incident review
SEV1 and SEV2 incidents need a written report within five business days, covering timeline, root cause, contributing factors and action items with owners and due dates. Reports are blameless.

## Recurrence
An incident whose root cause matches an earlier incident within twelve months is flagged as recurring. Recurring incidents are reviewed at the monthly reliability review, and their open action items are escalated to the department head.

## Regulatory notification
Payment outages above 60 minutes affecting retail customers must be reported to the regulator by Compliance within 24 hours.
