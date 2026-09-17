"""Subscriber data model (WBS 3.2-a)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

IMSI_RE = re.compile(r"^\d{15}$")
HEX32_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
HEX4_RE = re.compile(r"^[0-9A-Fa-f]{4}$")

# The reserved GSMA test PLMN (MCC 001 / MNC 01, per rfcs/rfc-0001) and the
# well-known 3GPP test vector already used in stack/core/subscribers.example.json.
# Safe to keep in git: not a real association's credentials (SECURITY.md).
TEST_PLMN = "00101"
TEST_KEY = "465B5CE8B199B49FAA5F0A2EE238A6BC"
TEST_OPC = "E8ED289DEBA952E4283B54E88E6183CA"


class SubscriberError(ValueError):
    """A subscriber field failed validation."""


@dataclass(frozen=True, slots=True)
class Subscriber:
    imsi: str
    key: str
    opc: str
    label: str = ""
    node_class_notes: str = ""
    amf: str = "8000"
    # RFC-0003 D1: Local Breakout by default for a roaming session -- the
    # visited island's SMF/UPF anchor the PDU session. False = Home-Routed
    # (anchored at this subscriber's home island). Written into every
    # slice[].session[] entry as upstream's own field name,
    # `lbo_roaming_allowed` (docs/_docs/tutorial/05-roaming.md section 2;
    # lib/dbi/session.c:172), by sync.py's _doc_js.
    lbo_roaming_allowed: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not IMSI_RE.match(self.imsi):
            raise SubscriberError(f"invalid imsi {self.imsi!r}: want 15 digits")
        if not HEX32_RE.match(self.key):
            raise SubscriberError(f"invalid key for {self.imsi}: want 32 hex chars")
        if not HEX32_RE.match(self.opc):
            raise SubscriberError(f"invalid opc for {self.imsi}: want 32 hex chars")
        if not HEX4_RE.match(self.amf):
            raise SubscriberError(f"invalid amf for {self.imsi}: want 4 hex chars")


def generate_test_imsi(existing: set[str]) -> str:
    """Next unused IMSI in the reserved test PLMN 001/01 range."""
    n = 1
    while True:
        candidate = f"{TEST_PLMN}{n:010d}"
        if candidate not in existing:
            return candidate
        n += 1
