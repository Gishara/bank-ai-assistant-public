---
doc_id: "SPEC-PAY-010"
title: "QR Instant Payments v2"
department: "product"
document_type: "product_spec"
access_level: "internal"
created_date: "2026-04-02"
author: "E1009"
author_name: "Sanduni Abeysekara"
tags: [spec, qr, payments]
---

# SPEC-PAY-010: QR Instant Payments v2

## Goal
Let customers pay any merchant QR code in under 5 seconds, including codes issued by other banks.

## Scope
- Scan merchant-presented QR codes that follow the national standard.
- Pay from savings or current accounts.
- Per-transaction limit LKR 200,000; daily limit LKR 500,000.
- No customer fee. Merchant fees follow the merchant tariff only.

## Non-functional requirements
- p95 end-to-end time under 3 seconds.
- Availability 99.9% monthly.
- Partner certificates renewed automatically through the certificate inventory.

## Success metrics
Monthly active QR payers, payment success rate above 99.5%, and fee-related complaints at zero.

## Open questions
Refund flow for merchant-initiated reversals.
