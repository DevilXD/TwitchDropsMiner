from __future__ import annotations

from utils import redact_sensitive, redact_url


def test_redacts_headers_and_nested_payloads() -> None:
    payload = {
        "headers": {
            "Authorization": "OAuth secret",
            "Cookie": "auth-token=secret",
            "User-Agent": "test",
        },
        "json": {
            "username": "someone",
            "password": "hunter2",
            "nested": {"access_token": "secret", "keep": 1},
        },
        "list": [{"refresh_token": "secret"}],
    }
    redacted = redact_sensitive(payload)
    assert redacted["headers"]["Authorization"] == "***"
    assert redacted["headers"]["Cookie"] == "***"
    assert redacted["headers"]["User-Agent"] == "test"
    assert redacted["json"]["password"] == "***"
    assert redacted["json"]["username"] == "someone"
    assert redacted["json"]["nested"]["access_token"] == "***"
    assert redacted["json"]["nested"]["keep"] == 1
    assert redacted["list"][0]["refresh_token"] == "***"


def test_redacts_proxy_userinfo_in_request_kwargs() -> None:
    redacted = redact_sensitive(
        {"proxy": "http://proxyuser:proxypass@127.0.0.1:8080"}
    )
    assert "proxyuser" not in redacted["proxy"]
    assert "proxypass" not in redacted["proxy"]
    assert "127.0.0.1:8080" in redacted["proxy"]


def test_redacts_sensitive_query_values_only() -> None:
    url = "https://usher.ttvnw.net/channel/hls/x.m3u8?sig=secret&token=secret&foo=bar"
    redacted = redact_url(url)
    assert "sig=***" in redacted
    assert "token=***" in redacted
    assert "foo=bar" in redacted
    assert "secret" not in redacted


def test_redact_url_hides_tokens_in_fragments() -> None:
    redacted = redact_url("https://www.twitch.tv/#access_token=secret&foo=bar")
    assert "secret" not in redacted
    assert "foo=bar" in redacted


def test_redact_url_hides_proxy_userinfo() -> None:
    redacted = redact_url("http://proxyuser:proxypass@127.0.0.1:8080/path")
    assert "proxyuser" not in redacted
    assert "proxypass" not in redacted
    assert "127.0.0.1:8080" in redacted


def test_redact_url_leaves_plain_urls_alone() -> None:
    assert redact_url("https://example.com/path") == "https://example.com/path"
