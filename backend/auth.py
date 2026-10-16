"""Password utilities and local synthetic demo accounts."""
from __future__ import annotations
import hashlib
import hmac
import secrets

ROLES = {"doctor", "reviewer", "manager", "administrator"}
DEMO_ACCOUNTS = (
    ("doctor@demo.org", "Dr. Demo", "doctor", "DoctorDemo2026!"),
    ("reviewer@demo.org", "Reviewer Demo", "reviewer", "ReviewerDemo2026!"),
    ("manager@demo.org", "Manager Demo", "manager", "ManagerDemo2026!"),
    ("admin@demo.org", "Administrator Demo", "administrator", "AdminDemo2026!"),
)
PASSWORD_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    scheme, iterations, salt, expected = encoded.split("$", 3)
    if scheme != "pbkdf2_sha256":
        raise ValueError("Unsupported password hash scheme.")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


_DUMMY_PASSWORD_HASH = hash_password("MetricBridge invalid account timing value")


def verify_unknown_account(password: str) -> None:
    verify_password(password, _DUMMY_PASSWORD_HASH)
