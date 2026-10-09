---
doc_id: "POL-RSK-004"
title: "Fraud Monitoring Thresholds"
department: "risk"
document_type: "policy"
access_level: "confidential"
created_date: "2026-02-28"
author: "E1006"
author_name: "Ishara Gunasekara"
tags: [fraud, risk, thresholds, cards]
---

# POL-RSK-004: Fraud Monitoring Thresholds

## Scoring thresholds
| Channel | Decline above | Step-up between | Approve below |
|---|---|---|---|
| Card not present | 820 | 640–820 | 640 |
| POS chip and PIN | 900 | 760–900 | 760 |
| Contactless | 860 | 700–860 | 700 |
| Instant transfer | 800 | 600–800 | 600 |

## Fallback policy when the provider is unavailable
If the external score is unavailable or slower than 800 ms, the local rules engine decides. In fallback mode:
- card-not-present transactions above LKR 150,000 are declined,
- contactless transactions are approved up to the contactless limit,
- all other transactions follow local rules.
Fallback mode is logged and reported to Fraud Analytics daily.

## Review
Thresholds are reviewed monthly against the false positive rate and confirmed fraud losses.
