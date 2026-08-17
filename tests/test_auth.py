import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.auth import (  # noqa: E402
    TokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_correct_password():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h)


def test_verify_rejects_wrong_password():
    h = hash_password("correct-horse-battery-staple")
    assert not verify_password("wrong-password", h)


def test_hash_uses_random_salt():
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2
    assert verify_password("same-password", h1)
    assert verify_password("same-password", h2)


def test_token_roundtrip():
    token = create_token({"user_id": 42})
    payload = decode_token(token)
    assert payload["user_id"] == 42
    assert "exp" in payload


def test_token_tampering_rejected():
    token = create_token({"user_id": 1})
    payload_b64, sig_b64 = token.split(".")
    tampered = payload_b64 + "x." + sig_b64
    try:
        decode_token(tampered)
        assert False, "expected TokenError"
    except TokenError:
        pass


def test_expired_token_rejected():
    token = create_token({"user_id": 1}, ttl_seconds=-10)
    try:
        decode_token(token)
        assert False, "expected TokenError"
    except TokenError:
        pass


def test_malformed_token_rejected():
    try:
        decode_token("not-a-real-token")
        assert False, "expected TokenError"
    except TokenError:
        pass
