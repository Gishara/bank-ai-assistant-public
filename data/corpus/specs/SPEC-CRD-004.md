---
doc_id: "SPEC-CRD-004"
title: "Card Tokenization for Mobile Wallets"
department: "product"
document_type: "product_spec"
access_level: "internal"
created_date: "2025-12-10"
author: "E1015"
author_name: "Shehani Karunaratne"
tags: [spec, cards, tokenization, wallets]
---

# SPEC-CRD-004: Card Tokenization for Mobile Wallets

## Goal
Allow customers to add Bank debit and credit cards to mobile wallets.

## Requirements
- Token provisioning with in-app verification or OTP.
- Token lifecycle events (suspend, resume, delete) synced with card status.
- Cryptogram validation through the HSM gateway.

## Capacity impact
Tokenized transactions add one cryptogram validation per payment. Cryptography Services estimates a 15% increase in HSM sessions at peak within six months of launch.

## Launch
Planned for February 2026.
