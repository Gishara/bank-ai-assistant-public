---
doc_id: "POL-SEC-003"
title: "Data Classification and Handling Standard"
department: "security"
document_type: "policy"
access_level: "public"
created_date: "2025-03-15"
author: "E1007"
author_name: "Chamari Rathnayake"
tags: [security, data-classification, policy]
---

# POL-SEC-003: Data Classification and Handling Standard

## Classification levels
| Level | Description | Examples |
|---|---|---|
| Public | Approved for release outside the Bank | Product brochures, published rates |
| Internal | For all staff; low impact if disclosed | Runbooks, architecture overviews, most incident reports |
| Confidential | Limited to staff with a business need | Fraud thresholds, security incidents, database recovery procedures |
| Restricted | Named individuals only; severe impact if disclosed | Cryptographic key procedures, HSM operations, customer PIN data |

## Handling
- Internal and above must not be pasted into external AI tools or public file sharing.
- Confidential documents are shared by link with access control, never as attachments.
- Restricted material is never stored outside its system of record.

## Labelling
Every document carries its classification in its metadata. Systems that index documents, including search and AI assistants, must preserve and enforce this label.
