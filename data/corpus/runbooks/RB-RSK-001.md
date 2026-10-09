---
doc_id: "RB-RSK-001"
title: "Runbook: Fraud Scoring Degraded Mode"
department: "risk"
document_type: "runbook"
access_level: "internal"
created_date: "2026-06-10"
author: "E1006"
author_name: "Ishara Gunasekara"
tags: [runbook, fraud, vendor]
---

# RB-RSK-001: Runbook: Fraud Scoring Degraded Mode

## Symptoms
- Fraud scoring latency above 800 ms or error rate above 5%.
- Circuit breaker open alert.

## Check
1. Confirm the breaker opened. If latency is high but the breaker is closed, check the configured timeout; it must be 800 ms.
2. Check the VeriScore status page and the vendor bridge.

## Act
3. If the breaker is not opening, force fallback with the `fraud.fallback.force` flag. On-call may do this without approval.
4. Notify Fraud Analytics; they monitor fallback losses.
5. Return to normal scoring only after 10 minutes of healthy vendor latency.

## Reporting
Fallback periods longer than 60 minutes are reported to the Head of Risk.
