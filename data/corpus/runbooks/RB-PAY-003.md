---
doc_id: "RB-PAY-003"
title: "Runbook: Settlement Batch Overrun"
department: "payments"
document_type: "runbook"
access_level: "internal"
created_date: "2026-08-20"
author: "E1005"
author_name: "Tharindu Silva"
tags: [runbook, settlement, batch, database]
---

# RB-PAY-003: Runbook: Settlement Batch Overrun

## Symptoms
- Batch overrun alert at 06:30.
- Lock wait time on the ledger above 500 ms.
- Authorization or transfer timeouts on accounts linked to settlement or fees.

## Act
1. Confirm the automatic pause triggered. If not, pause the batch manually at the next checkpoint.
2. Find blocking sessions: query `pg_locks` joined with `pg_stat_activity` for sessions from the batch user.
3. If a single step holds locks for more than 60 seconds, cancel that step. Do not cancel posting steps mid-commit.
4. Resume after 09:30, or earlier if the incident commander agrees.

## Escalation
Database Engineering on-call, then Payments Engineering head (E1001) for business decisions on delaying settlement.

## Notes
Delaying settlement past 12:00 must be reported to Compliance because merchant payouts are affected.
