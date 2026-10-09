---
doc_id: "ARC-PAY-001"
title: "Card Payments Platform Architecture"
department: "payments"
document_type: "architecture"
access_level: "internal"
created_date: "2025-07-10"
author: "E1016"
author_name: "Janaka Dissanayake"
tags: [architecture, cards, payments]
---

# ARC-PAY-001: Card Payments Platform Architecture

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
