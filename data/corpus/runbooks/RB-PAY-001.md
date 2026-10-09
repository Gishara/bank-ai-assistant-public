---
doc_id: "RB-PAY-001"
title: "Runbook: HSM Session Saturation"
department: "payments"
document_type: "runbook"
access_level: "internal"
created_date: "2026-05-20"
author: "E1008"
author_name: "Malith Herath"
tags: [runbook, hsm, cards]
---

# RB-PAY-001: Runbook: HSM Session Saturation

## Symptoms
- HSM utilization alert above 80%.
- Card authorization latency p95 above 1.5 s and rising decline code 91.
- ATM PIN failures at the same time as card declines.

## Check
1. Open the HSM gateway dashboard: active sessions, queue depth, wait time.
2. If active sessions equal the configured maximum and queue depth is growing, this runbook applies.
3. Check appliance CPU. Above 85% means more sessions will not help; go to step 6.

## Act
4. Raise the session maximum by 25% using the runtime setting. This is a standard change; record it afterwards.
5. Watch queue depth for 3 minutes.
6. If appliances are saturated, confirm both appliances are active. Bring any standby appliance into the pool.
7. Escalate to Cryptography Services lead (E1008) if not recovered in 15 minutes.

## After
- Record the peak session count in the incident report.
- Check that the autoscaler maximum is above the new peak.

## Related
ARC-PAY-001, POL-SEC-009 (restricted).
