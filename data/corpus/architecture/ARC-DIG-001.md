---
doc_id: "ARC-DIG-001"
title: "Mobile Banking Backend Architecture"
department: "product"
document_type: "architecture"
access_level: "internal"
created_date: "2025-10-02"
author: "E1010"
author_name: "Nuwan Bandara"
tags: [architecture, mobile, digital]
---

# ARC-DIG-001: Mobile Banking Backend Architecture

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
