"""File-level encryption for the subscriber store (WBS 3.2-a).

Chosen over SQLCipher (see sim-tools/README.md "Storage & encryption"):
SQLCipher needs a compiled native extension with no universal pip wheel,
which would break a plain `pipx install` on a volunteer's unprepared
machine. AES-256-GCM with a scrypt-derived key gives the same
"unreadable without the passphrase" property using only the pure-Python
`cryptography` wheel already pinned in pyproject.toml.
"""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"RESCSIM1"
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32


class DecryptionError(Exception):
    """Wrong passphrase, or the file is not a resccom-sim store."""


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=2**14, r=8, p=1)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt(plaintext: bytes, passphrase: str) -> bytes:
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, MAGIC)
    return MAGIC + salt + nonce + ciphertext


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if blob[: len(MAGIC)] != MAGIC:
        raise DecryptionError("not a resccom-sim store file")
    offset = len(MAGIC)
    salt = blob[offset : offset + SALT_LEN]
    offset += SALT_LEN
    nonce = blob[offset : offset + NONCE_LEN]
    offset += NONCE_LEN
    ciphertext = blob[offset:]
    key = _derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag as exc:
        raise DecryptionError("wrong passphrase or corrupted store") from exc
