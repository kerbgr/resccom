"""island_init.crypto (2.1-c): keypairs, signing, tamper detection."""
import base64

import pytest

from island_init.crypto import (
    SignatureVerificationError,
    canonical_payload,
    fingerprint_of,
    generate_signing_keypair,
    generate_wireguard_keypair,
    sign_document,
    verify_document,
)


def test_generate_signing_keypair_produces_matching_fingerprint():
    keypair = generate_signing_keypair()
    raw = base64.b64decode(keypair.public_key_b64)
    assert len(raw) == 32
    assert keypair.fingerprint == fingerprint_of(raw)
    assert keypair.fingerprint.startswith("SHA256:")


def test_generate_wireguard_keypair_is_32_raw_bytes_each():
    private_b64, public_b64 = generate_wireguard_keypair()
    assert len(base64.b64decode(private_b64)) == 32
    assert len(base64.b64decode(public_b64)) == 32
    assert private_b64 != public_b64


def test_sign_and_verify_round_trip():
    keypair = generate_signing_keypair()
    data = {"profile": "lab", "island": {"id": "x", "signing_public_key": keypair.public_key_b64}}
    data["signature"] = sign_document(data, keypair)
    verify_document(data)  # raises on failure


def test_canonical_payload_excludes_signature_and_is_order_independent():
    a = {"b": 2, "a": 1, "signature": {"value": "whatever"}}
    b = {"a": 1, "signature": {"value": "different"}, "b": 2}
    assert canonical_payload(a) == canonical_payload(b)


def test_verify_document_rejects_tampered_field():
    keypair = generate_signing_keypair()
    data = {"profile": "lab", "island": {"id": "x", "signing_public_key": keypair.public_key_b64}}
    data["signature"] = sign_document(data, keypair)
    data["profile"] = "production"  # tamper after signing
    with pytest.raises(SignatureVerificationError, match="tampered"):
        verify_document(data)


def test_verify_document_rejects_wrong_public_key():
    keypair = generate_signing_keypair()
    other = generate_signing_keypair()
    data = {"profile": "lab", "island": {"id": "x", "signing_public_key": keypair.public_key_b64}}
    data["signature"] = sign_document(data, keypair)
    data["island"]["signing_public_key"] = other.public_key_b64
    with pytest.raises(SignatureVerificationError):
        verify_document(data)


def test_verify_document_requires_public_key_present():
    data = {"island": {}, "signature": {"algorithm": "ed25519", "value": "x", "public_key_fingerprint": "y"}}
    with pytest.raises(SignatureVerificationError, match="signing_public_key"):
        verify_document(data)


def test_verify_document_rejects_unknown_algorithm():
    data = {"island": {"signing_public_key": "x"}, "signature": {"algorithm": "rsa"}}
    with pytest.raises(SignatureVerificationError, match="unsupported"):
        verify_document(data)
