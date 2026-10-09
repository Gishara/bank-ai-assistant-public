"""Operational runbooks."""

RUNBOOKS = [
    dict(
        id="RB-PAY-001", title="Runbook: HSM Session Saturation", department="payments",
        access="internal", date="2026-05-20", author="E1008", tags=["runbook", "hsm", "cards"],
        body="""
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
""",
    ),
    dict(
        id="RB-SEC-002", title="Runbook: Partner TLS Certificate Failure", department="security",
        access="internal", date="2026-04-18", author="E1008", tags=["runbook", "tls", "certificates", "switch"],
        body="""
## Symptoms
- Handshake errors in connector logs: "certificate expired", "unable to get local issuer certificate", "bad certificate".
- Synthetic transfer monitor failing while the network link is up.

## Diagnose
1. Run `openssl s_client -connect <partner-host>:443 -showcerts` from a connector node.
2. If the Bank's client certificate is expired, go to Renew.
3. If the partner's chain does not verify, compare its intermediate CA with the trust store, then go to Trust store.

## Renew
4. Request an emergency certificate from Cryptography Services on-call.
5. Deploy to all connector nodes; restart one node at a time.
6. Replay the outbound queue.

## Trust store
7. Add the partner's new intermediate CA to the trust store configuration.
8. Reload configuration (supported from September 2026) or redeploy.

## Prevention
Every partner-facing certificate must be in the certificate inventory with a named owner. Expiry alerts page the owning on-call at 30, 14 and 3 days.
""",
    ),
    dict(
        id="RB-PAY-003", title="Runbook: Settlement Batch Overrun", department="payments",
        access="internal", date="2026-08-20", author="E1005", tags=["runbook", "settlement", "batch", "database"],
        body="""
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
""",
    ),
    dict(
        id="RB-RSK-001", title="Runbook: Fraud Scoring Degraded Mode", department="risk",
        access="internal", date="2026-06-10", author="E1006", tags=["runbook", "fraud", "vendor"],
        body="""
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
""",
    ),
    dict(
        id="RB-DIG-001", title="Runbook: Mobile Login Failures", department="product",
        access="internal", date="2025-12-15", author="E1010", tags=["runbook", "mobile", "authentication"],
        body="""
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
""",
    ),
    dict(
        id="RB-PLT-004", title="Runbook: Ledger Database Failover", department="platform",
        access="confidential", date="2026-03-02", author="E1005", tags=["runbook", "database", "failover"],
        body="""
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
""",
    ),
    dict(
        id="RB-OPS-001", title="Incident Commander Checklist", department="platform",
        access="internal", date="2025-09-05", author="E1011", tags=["runbook", "incident", "process"],
        body="""
## First 10 minutes
- Declare severity using POL-OPS-001.
- Open the bridge and the incident channel.
- Name a scribe and a communications lead.

## Every 15 minutes
- Post a status update: impact, current hypothesis, next action, next update time.

## Decisions
- Prefer mitigation over diagnosis: roll back, fail over, or bypass first.
- Approve emergency changes with one senior engineer.

## Closing
- Confirm recovery with metrics, not opinions.
- Schedule the post-incident review within five business days.
- If the root cause matches a previous incident, mark the incident as recurring.
""",
    ),
]
