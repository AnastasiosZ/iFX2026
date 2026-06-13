"""
Password hashing and session tokens.

Passwords are never stored in plaintext. We use PBKDF2-HMAC-SHA256 (stdlib, no
external dependency) with a per-user random salt and a high iteration count.
Each user gets a unique salt, so identical passwords produce different hashes
and precomputed-hash ("rainbow table") attacks don't apply.

Login tokens are opaque random strings handed to the client and mapped to a
user in memory for the lifetime of the process — fine for a hackathon demo.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Cost factor. 200k iterations is comfortably above the OWASP floor while still
# being instant on a laptop for a demo's handful of logins.
_ITERATIONS = 200_000
_ALGO = "sha256"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """
    Return (salt_hex, hash_hex). Generates a fresh 16-byte salt if none given.
    Store BOTH; you need the salt to verify later.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time check of a candidate password against the stored hash."""
    _, candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, expected_hash)


def new_token() -> str:
    """A fresh opaque session token."""
    return secrets.token_hex(24)
