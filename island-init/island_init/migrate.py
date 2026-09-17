"""island-init migrate (3.3-b follow-up 5): bring an existing island.yaml
current with schema changes that added required fields after it was
generated -- 3.3-a's `node`, 3.3-b's `federation.peers`. Found live: the
already-generated lab instance failed `check` the moment 3.3-b shipped
while `island.sh up` kept running on its stale, already-rendered
configs, and nothing told the operator what had changed or how to fix it.

Deliberately not a generic schema-diff engine: it knows the specific
fields schema v0 has actually gained, with the same defaults `wizard.py`
gives a freshly built island, and re-signs if the document was already
signed (a migrated-but-now-unsigned document would itself fail `check`
under `profile: production`)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import crypto
from .wizard import DEFAULT_NODE_INTERNAL_BASE


class MigrateError(Exception):
    pass


def migrate_document(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Mutates and returns `data` (call with a plain dict you own, e.g. via
    a JSON round-trip of a loaded document) plus the list of field paths
    that were filled in. Idempotent: an already-current document comes
    back with an empty list."""
    changed: list[str] = []

    node = data.get("node")
    if not isinstance(node, dict):
        data["node"] = {"internal_base": DEFAULT_NODE_INTERNAL_BASE}
        changed.append("node.internal_base")
    elif not node.get("internal_base"):
        node["internal_base"] = DEFAULT_NODE_INTERNAL_BASE
        changed.append("node.internal_base")

    federation = data.get("federation")
    if not isinstance(federation, dict):
        data["federation"] = {"items": [], "peers": []}
        changed.append("federation.peers")
    elif "peers" not in federation:
        federation["peers"] = []
        changed.append("federation.peers")

    island = data.get("island")
    if isinstance(island, dict):
        overlay = island.get("overlay")
        if not isinstance(overlay, dict):
            island["overlay"] = {"endpoint": None, "wireguard_public_key": None, "address": None}
            changed.append("island.overlay.address")
        elif "address" not in overlay:
            overlay["address"] = None
            changed.append("island.overlay.address")

    return data, changed


def resign(data: dict[str, Any], secrets_dir: Path) -> None:
    """Re-signs `data` in place using the private key at
    secrets/<island id>/signing.key -- only called when the document was
    already signed (an unsigned lab document stays unsigned; migrate
    doesn't sign what wasn't signed to begin with)."""
    island = data.get("island") or {}
    island_id = island.get("id")
    fingerprint = island.get("signing_key_fingerprint")
    if not island_id or not fingerprint:
        raise MigrateError("document is signed but island.id or signing_key_fingerprint is missing -- cannot re-sign")
    key_path = secrets_dir / island_id / "signing.key"
    if not key_path.exists():
        raise MigrateError(f"document is signed but {key_path} does not exist -- cannot re-sign without the private key")
    signing = crypto.signing_keypair_from_private_b64(key_path.read_text(encoding="utf-8").strip())
    if signing.fingerprint != fingerprint:
        raise MigrateError(
            f"the private key at {key_path} does not match this document's declared "
            f"signing_key_fingerprint ({fingerprint!r} vs {signing.fingerprint!r}) -- cannot re-sign"
        )
    data["signature"] = crypto.sign_document(data, signing)
