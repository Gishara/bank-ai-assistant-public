---
doc_id: "SPEC-PAY-012"
title: "Merchant Settlement Dashboard"
department: "product"
document_type: "product_spec"
access_level: "internal"
created_date: "2026-01-20"
author: "E1009"
author_name: "Sanduni Abeysekara"
tags: [spec, merchants, settlement, reporting]
---

# SPEC-PAY-012: Merchant Settlement Dashboard

## Goal
Give merchants a near real-time view of settlements, fees and chargebacks.

## Requirements
- Settlement figures no more than 15 minutes old.
- Show a staleness banner when data is older than 15 minutes.
- CSV and PDF statement download.

## Data source
Read replica of the ledger database, so dashboard queries never load the primary.
