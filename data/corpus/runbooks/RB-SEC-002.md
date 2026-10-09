---
doc_id: "RB-SEC-002"
title: "Runbook: Partner TLS Certificate Failure"
department: "security"
document_type: "runbook"
access_level: "internal"
created_date: "2026-04-18"
author: "E1008"
author_name: "Malith Herath"
tags: [runbook, tls, certificates, switch]
---

# RB-SEC-002: Runbook: Partner TLS Certificate Failure

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
