---
doc_id: "ARC-PAY-003"
title: "End-of-Day Settlement Architecture"
department: "payments"
document_type: "architecture"
access_level: "internal"
created_date: "2026-07-28"
author: "E1016"
author_name: "Janaka Dissanayake"
tags: [architecture, settlement, batch, database]
---

# ARC-PAY-003: End-of-Day Settlement Architecture

## Purpose
Posts the day's card, transfer and QR settlements to the general ledger, calculates merchant fees, and runs period-end steps such as interest capitalization.

## Schedule
Runs from 01:00 with a window ending at 06:30, before morning transaction volume rises.

## Design standard (revised July 2026)
- No database transaction may hold row locks for more than 2 seconds.
- Postings commit in batches of at most 2,000 rows.
- Every step must be restartable from a checkpoint.
- If the batch is still running at 06:30 it pauses automatically at the next checkpoint and resumes after 09:30.
- New steps, including period-end steps, are reviewed against this standard by the Architecture Office.

## Why
Settlement and live payments update the same settlement, fee and customer accounts. Long transactions in the batch block live authorizations, which time out. This pattern caused incidents in August 2025, October 2025, January 2026 and June 2026.

## Monitoring
Batch progress, lock wait time on the ledger, and projected completion time are published every five minutes.
