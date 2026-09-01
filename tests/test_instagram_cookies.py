"""Tests for Instagram cookie-auth option building (no network — just verifies the
settings-to-yt-dlp-options mapping used for profile listing and downloads)."""

import pytest

from saad_sales_gpt.config import settings
from saad_sales_gpt.ingestion.instagram import _cookie_opts


def test_no_cookies_configured_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_cookies_from_browser", None)
    monkeypatch.setattr(settings, "instagram_cookies_file", None)

    assert _cookie_opts() == {}


def test_cookies_from_browser_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_cookies_from_browser", "chrome")
    monkeypatch.setattr(settings, "instagram_cookies_file", "/tmp/cookies.txt")

    assert _cookie_opts() == {"cookiesfrombrowser": ("chrome",)}


def test_cookies_file_used_when_no_browser_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "instagram_cookies_from_browser", None)
    monkeypatch.setattr(settings, "instagram_cookies_file", "/tmp/cookies.txt")

    assert _cookie_opts() == {"cookiefile": "/tmp/cookies.txt"}
