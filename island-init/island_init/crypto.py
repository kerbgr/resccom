"""Signing + overlay keypairs for island.yaml (2.1-c, RFC-0005 D1/D4).

Ed25519 for the document signature (small keys, fast, no parameter
choices to get wrong); X25519 for the WireGuard overlay key, generated
in WireGuard's own raw-base64 format so the value that lands in
island.yaml's overlay.wireguard_public_key is usable as-is by `wg`.

Signing is over a canonical JSON encoding of the *parsed* island.yaml
document (with the `signature` key itself removed), not the raw YAML
bytes -- island.yaml is only ever produced by island-init (RFC-0005 D1:
"no hand-edited per-service files"), so what must be tamper-evident is
the semantic content, not incidental re-serialization whitespace.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

SIGNATURE_ALGORITHM = "ed25519"


@dataclass(frozen=True, slots=True)
class SigningKeypair:
    private_key: Ed25519PrivateKey
    public_key_b64: str
    fingerprint: str  # "SHA256:<base64 of sha256(raw public key bytes)>"

    def private_key_b64(self) -> str:
        raw = self.private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        return base64.b64encode(raw).decode("ascii")


def fingerprint_of(public_key_raw: bytes) -> str:
    digest = hashlib.sha256(public_key_raw).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def generate_signing_keypair() -> SigningKeypair:
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SigningKeypair(
        private_key=private_key,
        public_key_b64=base64.b64encode(public_raw).decode("ascii"),
        fingerprint=fingerprint_of(public_raw),
    )


def generate_wireguard_keypair() -> tuple[str, str]:
    """Returns (private_key_b64, public_key_b64) in `wg genkey`/`wg pubkey` format."""
    private_key = X25519PrivateKey.generate()
    private_raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (
        base64.b64encode(private_raw).decode("ascii"),
        base64.b64encode(public_raw).decode("ascii"),
    )


def wireguard_public_key_from_private_b64(private_key_b64: str) -> str:
    """The `wg pubkey` of a raw-base64 WireGuard private key (3.3-b follow-up
    4: lets `island-init check` and `wg-up.sh` both derive the real public
    key from the host-side secret and catch it drifting from what
    island.yaml declares, instead of trusting the declared value blindly."""
    raw = base64.b64decode(private_key_b64)
    private_key = X25519PrivateKey.from_private_bytes(raw)
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(public_raw).decode("ascii")


def signing_keypair_from_private_b64(private_key_b64: str) -> SigningKeypair:
    """Reconstructs a full SigningKeypair (public key + fingerprint included)
    from just the raw-base64 private half written by `write_secrets` --
    needed to re-sign a document (`island-init migrate`, the two-island
    harness's transient peered copies) without generating a new identity."""
    raw = base64.b64decode(private_key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SigningKeypair(
        private_key=private_key,
        public_key_b64=base64.b64encode(public_raw).decode("ascii"),
        fingerprint=fingerprint_of(public_raw),
    )


def canonical_payload(data: dict) -> bytes:
    """The exact bytes a signature covers: `data` minus its own `signature`
    key, as compact, sorted-key JSON. Deterministic regardless of YAML
    key order or formatting."""
    unsigned = {k: v for k, v in data.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_document(data: dict, keypair: SigningKeypair) -> dict:
    """Returns the `signature` block to attach to `data` (does not mutate `data`)."""
    payload = canonical_payload(data)
    signature = keypair.private_key.sign(payload)
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "public_key_fingerprint": keypair.fingerprint,
        "value": base64.b64encode(signature).decode("ascii"),
    }


class SignatureVerificationError(Exception):
    """island.yaml carries a signature block that doesn't verify."""


def verify_document(data: dict) -> None:
    """Raises SignatureVerificationError if `data["signature"]` doesn't verify
    against `data["island"]["signing_public_key"]` over `data` minus
    `signature`. Callers must check `data.get("signature")` is truthy first
    -- an absent signature is not a verification failure, just unsigned."""
    signature = data.get("signature") or {}
    algorithm = signature.get("algorithm")
    if algorithm != SIGNATURE_ALGORITHM:
        raise SignatureVerificationError(f"unsupported signature.algorithm {algorithm!r}")

    public_key_b64 = ((data.get("island") or {}).get("signing_public_key")) or None
    if not public_key_b64:
        raise SignatureVerificationError("signature present but island.signing_public_key is null/missing")

    try:
        public_raw = base64.b64decode(public_key_b64)
        public_key = Ed25519PublicKey.from_public_bytes(public_raw)
        signature_raw = base64.b64decode(signature["value"])
    except (KeyError, ValueError) as exc:
        raise SignatureVerificationError(f"malformed signature or public key: {exc}") from exc

    try:
        public_key.verify(signature_raw, canonical_payload(data))
    except InvalidSignature as exc:
        raise SignatureVerificationError("signature does not match document contents (tampered?)") from exc
