"""Semantic validation beyond JSON Schema shape (2.1-a step 3, extended 2.1-c).

Four rule groups, matching TASKS.md's acceptance criteria:
  1. PCI uniqueness per island (across every site's cells).
  2. Declared IPv4 prefixes must not overlap.
  3. `profile: production` must not carry lab-only values: the reserved
     test PLMN/IMSI block, a null/placeholder signing or WireGuard key,
     a placeholder association name/operator contact, or no signature.
  4. A present `signature` block must cryptographically verify (2.1-c
     acceptance: "tampering one byte of a signed island.yaml makes check
     fail") -- checked regardless of profile, since an unsigned lab file
     has no signature block to begin with.

Each check is defensive about shape (an already-schema-invalid document
may be missing keys) -- it skips what it can't find rather than raising,
since schema validation reports missing/malformed fields on its own.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from . import crypto
from .issues import Issue
from .yaml_io import line_of, path_str

# sim-tools/resccom_sim/model.py's TEST_PLMN / TEST_KEY / TEST_OPC: the
# reserved 3GPP test vectors, safe in a lab but never a real association's.
TEST_MCC = "001"
TEST_MNC = "01"
TEST_IMSI_PREFIX = "00101"

# stack/services/config/portal/server.py's literal placeholder text.
ASSOCIATION_NAME_PLACEHOLDER = "[local association name]"


def check_pci_uniqueness(data: Any, root: Any) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[int, tuple[Any, ...]] = {}
    sites = data.get("sites") or []
    for si, site in enumerate(sites):
        cells = (site or {}).get("cells") or []
        for ci, cell in enumerate(cells):
            pci = (cell or {}).get("pci")
            if pci is None:
                continue
            path = ("sites", si, "cells", ci, "pci")
            if pci in seen:
                first = seen[pci]
                issues.append(
                    Issue(
                        field=path_str(path),
                        message=f"duplicate PCI {pci} (already used at {path_str(first)})",
                        line=line_of(root, path),
                    )
                )
            else:
                seen[pci] = path
    return issues


def check_prefix_overlap(data: Any, root: Any) -> list[Issue]:
    issues: list[Issue] = []
    allocations = data.get("allocations") or {}
    services_prefix = allocations.get("services_prefix")
    ue_prefix = (allocations.get("ue_prefix") or {}).get("v4")
    if not services_prefix or not ue_prefix:
        return issues
    try:
        ue_net = ipaddress.ip_network(ue_prefix, strict=False)
        services_net = ipaddress.ip_network(services_prefix, strict=False)
    except ValueError:
        return issues  # malformed CIDR is a schema/format concern, not this check's
    if ue_net.overlaps(services_net):
        path = ("allocations", "services_prefix")
        issues.append(
            Issue(
                field=path_str(path),
                message=(
                    f"services_prefix {services_prefix} overlaps ue_prefix.v4 {ue_prefix} "
                    "-- prefixes must not overlap"
                ),
                line=line_of(root, path),
            )
        )
    return issues


def check_production_profile(data: Any, root: Any) -> list[Issue]:
    issues: list[Issue] = []
    if data.get("profile") != "production":
        return issues

    allocations = data.get("allocations") or {}
    plmn = allocations.get("plmn") or {}
    if plmn.get("mcc") == TEST_MCC and plmn.get("mnc") == TEST_MNC:
        path = ("allocations", "plmn", "mcc")
        issues.append(
            Issue(
                field=path_str(path),
                message="production profile must not use the reserved test PLMN 001/01",
                line=line_of(root, path),
            )
        )

    imsi_block = allocations.get("imsi_block") or ""
    if imsi_block.startswith(TEST_IMSI_PREFIX):
        path = ("allocations", "imsi_block")
        issues.append(
            Issue(
                field=path_str(path),
                message=f"production profile must not use the reserved test IMSI block ({TEST_IMSI_PREFIX}...)",
                line=line_of(root, path),
            )
        )

    island = data.get("island") or {}
    if not island.get("signing_key_fingerprint"):
        path = ("island", "signing_key_fingerprint")
        issues.append(
            Issue(
                field=path_str(path),
                message="production island must have a real signing_key_fingerprint, not null/empty",
                line=line_of(root, path),
            )
        )

    overlay = island.get("overlay") or {}
    if not overlay.get("wireguard_public_key"):
        path = ("island", "overlay", "wireguard_public_key")
        issues.append(
            Issue(
                field=path_str(path),
                message="production island must have a real overlay.wireguard_public_key, not null/empty",
                line=line_of(root, path),
            )
        )

    services = data.get("services") or {}
    assoc_name = services.get("portal_association_name")
    if not assoc_name or assoc_name == ASSOCIATION_NAME_PLACEHOLDER:
        path = ("services", "portal_association_name")
        issues.append(
            Issue(
                field=path_str(path),
                message="production profile must set a real portal_association_name, not null/placeholder",
                line=line_of(root, path),
            )
        )

    contact = services.get("portal_operator_contact")
    if not contact:
        path = ("services", "portal_operator_contact")
        issues.append(
            Issue(
                field=path_str(path),
                message="production profile must set a real portal_operator_contact, not null/empty",
                line=line_of(root, path),
            )
        )

    if not island.get("signing_public_key"):
        path = ("island", "signing_public_key")
        issues.append(
            Issue(
                field=path_str(path),
                message="production island must have a real signing_public_key, not null/empty",
                line=line_of(root, path),
            )
        )

    if not data.get("signature"):
        issues.append(
            Issue(
                field="signature",
                message="production island must be signed (see island-init new)",
                line=None,
            )
        )

    return issues


def check_signature(data: Any, root: Any) -> list[Issue]:
    signature = data.get("signature")
    if not signature:
        return []  # unsigned is fine here; check_production_profile requires one when it matters
    try:
        crypto.verify_document(data)
    except crypto.SignatureVerificationError as exc:
        path = ("signature",)
        return [Issue(field=path_str(path), message=str(exc), line=line_of(root, path))]
    return []


ALL_CHECKS = (check_pci_uniqueness, check_prefix_overlap, check_production_profile, check_signature)


def run_semantic_checks(data: Any, root: Any) -> list[Issue]:
    issues: list[Issue] = []
    for check in ALL_CHECKS:
        issues.extend(check(data, root))
    return issues


def check_wireguard_key_matches(data: Any, root: Any, secrets_dir: Path | None) -> list[Issue]:
    """3.3-b follow-up 4: found live -- after the live two-island test,
    `secrets/lab/wireguard.key`'s public half no longer matched
    `island.yaml`'s declared `overlay.wireguard_public_key` (keys
    regenerated during testing, the fixture restored, nothing re-synced).
    Peers built from that stale declared value would never handshake, and
    nothing said why. Not folded into ALL_CHECKS/run_semantic_checks: this
    is the one check that needs filesystem access beyond the document
    itself, so callers (`check`, `render`) pass `secrets_dir` explicitly
    and skip it (pass None) where no meaningful secrets/ location exists
    (bare document validation with no repo context).

    Skips cleanly -- not a failure -- whenever there's nothing to compare:
    no declared key, no island id, or no key file at that path yet (a
    fresh island.yaml before its first `island-init new` has neither)."""
    if secrets_dir is None:
        return []
    island = data.get("island") or {}
    declared = (island.get("overlay") or {}).get("wireguard_public_key")
    island_id = island.get("id")
    if not declared or not island_id:
        return []
    key_path = secrets_dir / island_id / "wireguard.key"
    if not key_path.exists():
        return []
    path = ("island", "overlay", "wireguard_public_key")
    try:
        actual = crypto.wireguard_public_key_from_private_b64(key_path.read_text(encoding="utf-8").strip())
    except Exception as exc:  # noqa: BLE001 -- any malformed key file is a check failure, not a crash
        return [
            Issue(
                field=path_str(path),
                message=f"could not derive a public key from {key_path}: {exc}",
                line=line_of(root, path),
            )
        ]
    if actual != declared:
        return [
            Issue(
                field=path_str(path),
                message=(
                    f"declared wireguard_public_key does not match the private key at {key_path} "
                    f"(declared {declared!r}, derived from the key file {actual!r}) -- the key file "
                    "and island.yaml have drifted apart; regenerate one to match the other"
                ),
                line=line_of(root, path),
            )
        ]
    return []
