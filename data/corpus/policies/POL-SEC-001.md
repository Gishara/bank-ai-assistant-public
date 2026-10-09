---
doc_id: "POL-SEC-001"
title: "Information Security Policy"
department: "security"
document_type: "policy"
access_level: "internal"
created_date: "2025-06-01"
author: "E1007"
author_name: "Chamari Rathnayake"
tags: [security, policy, governance]
---

# POL-SEC-001: Information Security Policy

## Purpose
This policy sets the minimum security requirements for all information systems operated by the Bank. It applies to employees, contractors and third parties with access to Bank systems.

## Ownership
The Chief Information Security Officer owns this policy and reviews it every twelve months or after a material incident.

## Principles
- Information is protected according to its classification under POL-SEC-003.
- Access is granted on least privilege and reviewed quarterly (see POL-SEC-002).
- Every production change follows the change management policy (POL-OPS-002).
- Security events are logged centrally and retained for seven years.

## Third parties
Vendors that process customer data or sit in a payment path must pass a security assessment before go-live and every two years after. Contracts must include incident notification within 24 hours and a right to audit.

## Cryptography
Cryptographic keys that protect cardholder data or PINs are generated and stored only in hardware security modules. Key management procedures are defined in POL-SEC-009, which is restricted to Cryptography Services and Internal Audit.

## Exceptions
Exceptions require written approval from the CISO, a compensating control, and an expiry date no later than twelve months.
