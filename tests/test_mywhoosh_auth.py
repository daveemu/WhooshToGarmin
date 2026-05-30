"""Tests for the pure myWhoosh session/URL helpers."""

from __future__ import annotations

import base64
import json

from whooshtogarmin.mywhoosh_auth import (
    decode_jwt_exp,
    extract_token,
    is_trusted_download_url,
    session_is_valid,
    token_is_valid,
)


def _make_jwt(payload: dict) -> str:
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    header = seg(b'{"alg":"HS256","typ":"JWT"}')
    body = seg(json.dumps(payload).encode())
    return f"{header}.{body}.signature"


def test_decode_jwt_exp_reads_claim():
    assert decode_jwt_exp(_make_jwt({"exp": 2000000000})) == 2000000000.0


def test_decode_jwt_exp_rejects_malformed():
    assert decode_jwt_exp("not-a-jwt") is None
    assert decode_jwt_exp("a.b") is None
    assert decode_jwt_exp(_make_jwt({"no_exp": 1})) is None


def test_decode_jwt_exp_rejects_non_numeric_exp():
    assert decode_jwt_exp(_make_jwt({"exp": "soon"})) is None
    assert decode_jwt_exp(_make_jwt({"exp": True})) is None


def test_token_validity_uses_leeway():
    token = _make_jwt({"exp": 1000})
    assert token_is_valid(token, now=900, leeway_seconds=60) is True   # 100s left
    assert token_is_valid(token, now=950, leeway_seconds=60) is False  # 50s left
    assert token_is_valid(token, now=1001, leeway_seconds=60) is False  # expired


def test_token_validity_handles_none_and_garbage():
    assert token_is_valid(None) is False
    assert token_is_valid("") is False
    assert token_is_valid("garbage") is False


def test_extract_token_from_storage_state():
    state = {
        "origins": [
            {
                "origin": "https://event.mywhoosh.com",
                "localStorage": [
                    {"name": "other", "value": "x"},
                    {"name": "webToken", "value": "the-jwt"},
                ],
            }
        ]
    }
    assert extract_token(state) == "the-jwt"


def test_extract_token_missing():
    assert extract_token({"origins": []}) is None
    assert extract_token({}) is None


def test_session_is_valid():
    token = _make_jwt({"exp": 2000})
    state = {
        "origins": [
            {"localStorage": [{"name": "webToken", "value": token}]}
        ]
    }
    assert session_is_valid(state, now=1000) is True
    assert session_is_valid(state, now=1999) is False


def test_trusted_download_urls():
    assert is_trusted_download_url("https://bucket.s3.amazonaws.com/file.fit?sig=1")
    assert is_trusted_download_url("https://d123.cloudfront.net/file.fit")
    assert is_trusted_download_url("https://cdn.mywhoosh.com/a.fit")


def test_untrusted_download_urls():
    assert not is_trusted_download_url("http://bucket.s3.amazonaws.com/f.fit")  # not https
    assert not is_trusted_download_url("https://evil.com/f.fit")
    assert not is_trusted_download_url("https://amazonaws.com.evil.com/f.fit")
    assert not is_trusted_download_url(None)
    assert not is_trusted_download_url("")
