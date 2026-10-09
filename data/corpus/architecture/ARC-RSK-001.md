---
doc_id: "ARC-RSK-001"
title: "Fraud Scoring Integration"
department: "risk"
document_type: "architecture"
access_level: "confidential"
created_date: "2026-06-25"
author: "E1016"
author_name: "Janaka Dissanayake"
tags: [architecture, fraud, vendor, resilience]
---

# ARC-RSK-001: Fraud Scoring Integration

## Overview
Every card authorization and instant transfer is scored by VeriScore, an external fraud scoring service hosted in two regions. The Bank applies local rule overlays on top of the score.

## Target design (approved June 2026)
- Timeout of 800 ms per call, inside the 3 second authorization budget.
- Circuit breaker opens after 20% failures or slow calls over 30 seconds.
- When open, the local rules engine scores the transaction under the fallback policy in POL-RSK-004.
- Breaker state and fallback volume are exposed as metrics and alert after 5 minutes in fallback.

## Configuration control
Timeout and breaker settings are covered by a contract test in the build pipeline. A change to these values is a normal change.

## Vendor management
VeriScore must notify the Bank within 15 minutes of a regional incident. Monthly service reviews track latency p99 and availability.
