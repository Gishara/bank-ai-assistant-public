---
doc_id: "SPEC-DIG-021"
title: "Biometric Login for Mobile App 5.0"
department: "product"
document_type: "product_spec"
access_level: "internal"
created_date: "2026-05-05"
author: "E1010"
author_name: "Nuwan Bandara"
tags: [spec, mobile, biometrics, authentication]
---

# SPEC-DIG-021: Biometric Login for Mobile App 5.0

## Goal
Replace password entry with device biometrics for returning users.

## Requirements
- Enrol after a successful password login and OTP.
- Biometric unlock releases a device-bound key that signs the login challenge.
- Fall back to password after three failed biometric attempts.
- Re-enrol when the device biometrics change.

## Security
The private key never leaves the device's secure hardware. The server stores only the public key.

## Release
Version 5.0, staged rollout from August 2026.
