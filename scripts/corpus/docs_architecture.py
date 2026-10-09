"""Architecture documents."""

ARCHITECTURE = [
    dict(
        id="ARC-PAY-001", title="Card Payments Platform Architecture", department="payments",
        access="internal", date="2025-07-10", author="E1016", tags=["architecture", "cards", "payments"],
        body="""
## Context
The card payments platform authorizes about 1.1 million card transactions a day across POS, e-commerce, contactless and ATM channels. Peak load on festival days reaches 3.5 times the daily average.

## Components
- **card-auth-service**: stateless Java service, 12 pods across two data centers. Authorization budget is 3 seconds end to end (2 seconds for contactless).
- **hsm-gateway**: brokers cryptographic calls (PIN translation, CVV, ARQC validation) to the HSM appliances using a pool of sessions.
- **fraud-scoring-client**: calls the external VeriScore API and applies local rule overlays.
- **core-banking-adapter**: reserves funds and posts holds in the ledger.

## Authorization flow
1. Message arrives from the card network gateway.
2. Cryptographic checks through the HSM gateway.
3. Fraud score.
4. Funds check and hold through the core banking adapter.
5. Response to the network.

Steps 2 to 4 are synchronous. A delay in any dependency consumes the shared 3 second budget.

## Capacity
HSM sessions, fraud API concurrency and ledger connections are the three capacity limits. Each must be sized for projected peak, not last year's peak.

## Known risks
- Synchronous dependency on an external fraud provider (see ARC-RSK-001).
- Contention with the end-of-day settlement batch on shared ledger accounts (see ARC-PAY-003).
""",
    ),
    dict(
        id="ARC-PAY-002", title="National Payment Switch Integration", department="payments",
        access="internal", date="2025-05-22", author="E1004", tags=["architecture", "transfers", "switch", "tls"],
        body="""
## Purpose
Connects the Bank to the national payment switch for real-time interbank transfers and QR payments.

## Connectivity
- Dedicated leased lines from both data centers to the switch operator.
- Mutual TLS: the Bank presents a client certificate and validates the operator's server certificate against a local trust store.
- Hostname resolution uses the operator's private DNS zone through a conditional forwarder on the Bank's internal resolvers.

## Message flow
Outgoing transfers are queued in the outbound queue before sending, so messages are not lost during a link outage and can be replayed.

## Certificates
| Certificate | Issuer | Validity | Owner |
|---|---|---|---|
| Bank client certificate | Bank PKI | 2 years | Cryptography Services |
| Operator server certificate | Operator CA | Rotated by operator with notice | Switch Integration (trust store) |

Operator changes are announced through technical circulars. Switch Integration must review every circular.

## Availability target
99.95% monthly, measured by the synthetic transfer monitor every minute.
""",
    ),
    dict(
        id="ARC-PAY-003", title="End-of-Day Settlement Architecture", department="payments",
        access="internal", date="2026-07-28", author="E1016", tags=["architecture", "settlement", "batch", "database"],
        body="""
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
""",
    ),
    dict(
        id="ARC-RSK-001", title="Fraud Scoring Integration", department="risk",
        access="confidential", date="2026-06-25", author="E1016", tags=["architecture", "fraud", "vendor", "resilience"],
        body="""
## Overview
Every card authorization and instant transfer is scored by VeriScore, an external fraud scoring service hosted in two regions. The Bank applies local rule overlays on top of the score.

## Target design (approved June 2026)
- Timeout of 800 ms per call, inside the 3 second authorization budget.
- Circuit breaker opens after 20% failures or slow calls over 30 seconds.
- When open, the local rules engine scores the transaction under the fallback policy in POL-RSK-004.
- Breaker state and fallback volume are exposed as metrics and alert after 5 minutes in fallback.

## Configuration control
Timeout and breaker settings are covered by a contract test in the build pipeline. A change to these values is a normal change.

## Vendor management
VeriScore must notify the Bank within 15 minutes of a regional incident. Monthly service reviews track latency p99 and availability.
""",
    ),
    dict(
        id="ARC-DIG-001", title="Mobile Banking Backend Architecture", department="product",
        access="internal", date="2025-10-02", author="E1010", tags=["architecture", "mobile", "digital"],
        body="""
## Overview
The mobile banking app serves about 1.4 million active users. The backend is the mobile-banking-api, which aggregates identity, accounts, payments and notifications.

## Authentication
Customers log in with password plus device binding, or biometrics on supported devices. The identity service issues signed session tokens valid for 15 minutes with refresh.

## Token validation
API nodes validate tokens with the identity service's public keys, cached locally. Since December 2025, nodes refresh the key set when validation fails, so key rotation does not log users out.

## Dependencies
- identity-service for sessions and step-up
- core-banking-adapter for balances and transfers
- notification-service for OTPs and push messages

## Releases
App releases roll out in stages (5%, 20%, 50%, 100%) with crash-rate gates.
""",
    ),
]
