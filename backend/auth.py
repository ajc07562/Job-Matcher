"""
Password hashing and session tokens, implemented with the standard library only
(hashlib/hmac/base64/json) rather than adding passlib + PyJWT as dependencies.

Password hashing: PBKDF2-HMAC-SHA256 with a random salt per user, stored as
"iterations$salt_hex$hash_hex". This is the same primitive Django's default
hasher uses under the hood — it's a legitimate, not a toy, choice.

Session tokens: a minimal signed token (HMAC-SHA256 over a JSON payload),
functionally the same shape as a JWT (base64url(payload).base64url(signature))
without pulling in a JWT library. Verification uses hmac.compare_digest to
avoid timing attacks.

For a real production deployment you'd want a vetted library and a rotated
secret in a secrets manager — SECRET_KEY here defaults to a random value
generated at process start (see config.py) unless SESSION_SECRET is set in
the environment, which is enough for a portfolio/demo deployment but is
called out explicitly so it's not mistaken for production-hardened auth.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from backend.config import SECRET_KEY, TOKEN_TTL_SECONDS

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"{PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        iterations_str, salt, hash_hex = stored_hash.split("$")
        iterations = int(iterations_str)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return hmac.compare_digest(candidate.hex(), hash_hex)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(payload: dict, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_seconds
    payload_b64 = _b64url_encode(json.dumps(body, separators=(",", ":")).encode())
    signature = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{payload_b64}.{sig_b64}"


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise TokenError("Malformed token")

    expected_sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenError("Invalid signature")

    payload = json.loads(_b64url_decode(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise TokenError("Token expired")

    return payload
