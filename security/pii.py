"""Mask personal data in assistant output."""

from __future__ import annotations

import re

CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
NIC_RE = re.compile(r"\b(?:\d{9}[VvXx]|(?:19|20)\d{10})\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+94|0)7\d[ -]?\d{3}[ -]?\d{4}(?!\d)")
ACCOUNT_RE = re.compile(r"\b\d{10,16}\b")


def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask_pii(text: str) -> tuple[str, dict[str, int]]:
    counts = {"card": 0, "nic": 0, "phone": 0, "account": 0}

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            counts["card"] += 1
            return f"[card ending {digits[-4:]}]"
        return m.group()

    def sub(kind: str, label: str):
        def _f(m: re.Match) -> str:
            counts[kind] += 1
            return label
        return _f

    text = CARD_RE.sub(card, text)
    text = NIC_RE.sub(sub("nic", "[NIC redacted]"), text)
    text = PHONE_RE.sub(sub("phone", "[phone redacted]"), text)
    text = ACCOUNT_RE.sub(sub("account", "[account number redacted]"), text)
    return text, {k: v for k, v in counts.items() if v}
