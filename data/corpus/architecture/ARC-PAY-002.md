---
doc_id: "ARC-PAY-002"
title: "National Payment Switch Integration"
department: "payments"
document_type: "architecture"
access_level: "internal"
created_date: "2025-05-22"
author: "E1004"
author_name: "Ruwan Wickramasinghe"
tags: [architecture, transfers, switch, tls]
---

# ARC-PAY-002: National Payment Switch Integration

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
