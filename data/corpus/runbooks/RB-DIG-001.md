---
doc_id: "RB-DIG-001"
title: "Runbook: Mobile Login Failures"
department: "product"
document_type: "runbook"
access_level: "internal"
created_date: "2025-12-15"
author: "E1010"
author_name: "Nuwan Bandara"
tags: [runbook, mobile, authentication]
---

# RB-DIG-001: Runbook: Mobile Login Failures

## Symptoms
Login failure rate above 10% in the mobile app.

## Diagnose
1. Check identity service health and recent key rotations.
2. Check token validation errors on mobile-banking-api nodes.
3. Check notification-service OTP latency; slow OTPs look like login failures to customers.

## Act
- After key rotation: trigger key refresh on API nodes.
- OTP delays: switch SMS aggregator.
- App release: halt staged rollout.
