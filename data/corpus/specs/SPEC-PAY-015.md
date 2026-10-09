---
doc_id: "SPEC-PAY-015"
title: "Standing Orders v2"
department: "product"
document_type: "product_spec"
access_level: "internal"
created_date: "2026-08-12"
author: "E1009"
author_name: "Sanduni Abeysekara"
tags: [spec, standing-orders, payments]
---

# SPEC-PAY-015: Standing Orders v2

## Goal
Let customers create and manage standing orders in the mobile app, including to other banks.

## Requirements
- Weekly, monthly or custom schedules.
- Interbank orders sent through the payment switch at 08:00, after the settlement window and morning batch pause.
- Failed orders retried once at 12:00, then the customer is notified.

## Dependencies
payment-switch-connector, core-banking-adapter, notification-service.
