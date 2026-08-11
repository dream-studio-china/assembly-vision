"""Credential hashing unit tests (C1b)."""

from __future__ import annotations

from central_service.auth.passwords import CredentialHash, hash_credential, verify_credential


def test_hash_and_verify_roundtrip() -> None:
    stored = hash_credential("super-secret-token")
    assert verify_credential("super-secret-token", stored)


def test_wrong_token_fails() -> None:
    stored = hash_credential("super-secret-token")
    assert not verify_credential("different-token", stored)


def test_salts_are_unique_per_hash() -> None:
    first = hash_credential("same-token")
    second = hash_credential("same-token")
    assert first.salt != second.salt
    assert first.digest != second.digest
    assert verify_credential("same-token", first)
    assert verify_credential("same-token", second)


def test_malformed_stored_hash_fails_closed() -> None:
    assert not verify_credential("token", CredentialHash(salt="zz", digest="not-hex"))


def test_plaintext_is_never_stored() -> None:
    stored = hash_credential("super-secret-token")
    assert "super-secret-token" not in stored.salt
    assert "super-secret-token" not in stored.digest
