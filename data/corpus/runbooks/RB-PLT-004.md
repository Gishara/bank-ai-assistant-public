---
doc_id: "RB-PLT-004"
title: "Runbook: Ledger Database Failover"
department: "platform"
document_type: "runbook"
access_level: "confidential"
created_date: "2026-03-02"
author: "E1005"
author_name: "Tharindu Silva"
tags: [runbook, database, failover]
---

# RB-PLT-004: Runbook: Ledger Database Failover

## When to fail over
The primary is unavailable for more than 2 minutes, or storage on the primary is failing.

## Steps
1. Freeze the settlement batch.
2. Confirm the synchronous replica in the secondary data center is current (lag zero).
3. Promote the replica with the cluster manager; the virtual IP moves automatically.
4. Verify writes from core-banking-adapter.
5. Rebuild the old primary as a replica.

## Credentials
Failover requires the database break-glass account, retrieved from the privileged access vault with two-person approval.

## Expected impact
About 45 seconds of failed writes. Card authorizations retry automatically.
