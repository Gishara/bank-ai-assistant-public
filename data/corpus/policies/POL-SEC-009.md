---
doc_id: "POL-SEC-009"
title: "Cryptographic Key Management and HSM Operations"
department: "security"
document_type: "policy"
access_level: "restricted"
created_date: "2026-01-10"
author: "E1008"
author_name: "Malith Herath"
tags: [security, cryptography, hsm, keys]
---

# POL-SEC-009: Cryptographic Key Management and HSM Operations

## Key custodians
Master keys are split into three components held by three custodians from different teams. No custodian may hold more than one component of the same key.

## Key ceremonies
Key loading takes place in the secure room with two custodians and an Internal Audit witness. Ceremony scripts and logs are stored in the restricted vault.

## HSM administration
- Administrative access to HSM appliances requires two-person authorization.
- Session pool limits are operational settings and can be changed by Cryptography Services on-call as a standard change.
- Firmware updates are tested in the non-production cluster for 30 days.

## Key rotation
Zone master keys rotate every two years; PIN encryption keys every year.

## Compromise
A suspected key compromise is a SEV1 security incident. The CISO decides on key revocation within one hour.
