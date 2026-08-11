"""Credential hashing for pilot tokens (C1b).

Device upload tokens and administrator tokens are high-entropy secrets issued
once during bootstrap; only salted hashes are stored. scrypt is a memory-hard
KDF with a per-secret random salt, and verification uses a constant-time
comparison so token timing does not leak.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

_SALT_BYTES = 16
_DERIVED_KEY_BYTES = 64
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


@dataclass(frozen=True)
class CredentialHash:
    """Salted hash of a pilot credential; the plaintext is never persisted."""

    salt: str
    digest: str


def hash_credential(token: str) -> CredentialHash:
    """Return a salted scrypt hash for ``token``."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        token.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DERIVED_KEY_BYTES,
    )
    return CredentialHash(salt=salt.hex(), digest=digest.hex())


def verify_credential(token: str, stored: CredentialHash) -> bool:
    """Return whether ``token`` matches the stored salted hash."""
    try:
        salt = bytes.fromhex(stored.salt)
        expected = bytes.fromhex(stored.digest)
    except ValueError:
        return False
    computed = hashlib.scrypt(
        token.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DERIVED_KEY_BYTES,
    )
    return hmac.compare_digest(computed, expected)
