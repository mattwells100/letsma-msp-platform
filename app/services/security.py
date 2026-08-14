"""
Lightweight password hashing utility (PBKDF2-HMAC-SHA256 via Python's stdlib
`hashlib`), used instead of passlib/bcrypt to avoid brittle native-binding
version conflicts across platforms. Fully self-contained, no extra dependency.
"""
import hashlib
import hmac
import os
import base64

ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = hashed.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False
