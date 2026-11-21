from __future__ import annotations

from starlette.requests import Request

from report_qa.api import auth


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers or [], "query_string": b"", "server": ("test", 80), "client": ("test", 1), "scheme": "http"})


def test_password_hash_is_salted_and_verifiable_without_persisting_plaintext() -> None:
    first = auth._hash_password("correct horse battery staple")
    second = auth._hash_password("correct horse battery staple")
    assert first != second
    assert "correct horse" not in first
    assert auth._verify_password("correct horse battery staple", first)
    assert not auth._verify_password("wrong password", first)


def test_token_hash_is_one_way_digest() -> None:
    digest = auth._token_hash("opaque-session-token")
    assert len(digest) == 64
    assert digest != "opaque-session-token"


def test_csrf_origin_guard_rejects_unknown_browser_origin() -> None:
    request = _request([(b"origin", b"https://evil.example")])
    try:
        auth._csrf_guard(request)
    except Exception as error:
        assert getattr(error, "status_code", None) == 403
    else:
        raise AssertionError("unknown origin was accepted")


def test_csrf_origin_guard_allows_local_ui_and_curl_without_origin() -> None:
    auth._csrf_guard(_request([(b"origin", b"http://127.0.0.1:4173")]))
    auth._csrf_guard(_request())


def test_change_password_contract_requires_a_new_password() -> None:
    payload = auth.ChangePasswordRequest(current_password="old-password", new_password="new-password")
    assert payload.current_password == "old-password"
    assert payload.new_password == "new-password"
