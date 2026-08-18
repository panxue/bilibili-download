import json
import urllib.request
from unittest import mock

import pytest

from backend import main


def fake_nav_response(is_login: bool) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps({"data": {"isLogin": is_login}}).encode()
    # `with urlopen(...) as resp` must return the same resp via __enter__
    resp.__enter__.return_value = resp
    return resp


class TestCheckCookies:
    def test_empty_cookie_is_valid(self):
        assert main._check_cookies("") is None
        assert main._check_cookies("   ") is None

    def test_valid_cookie_passes(self):
        with mock.patch.object(
            urllib.request, "urlopen", return_value=fake_nav_response(True)
        ):
            assert main._check_cookies("SESSDATA=abc; bili_jct=def") is None

    def test_invalid_cookie_returns_error(self):
        with mock.patch.object(
            urllib.request, "urlopen", return_value=fake_nav_response(False)
        ):
            err = main._check_cookies("SESSDATA=expired")
        assert err is not None
        assert err["code"] == -3

    def test_network_error_treated_as_valid(self):
        with mock.patch.object(
            urllib.request, "urlopen", side_effect=urllib.request.URLError("boom")
        ):
            assert main._check_cookies("SESSDATA=abc") is None

    def test_malformed_json_treated_as_valid(self):
        resp = mock.MagicMock()
        resp.read.return_value = b"not-json"
        resp.__enter__.return_value = resp
        with mock.patch.object(urllib.request, "urlopen", return_value=resp):
            assert main._check_cookies("SESSDATA=abc") is None


@pytest.mark.parametrize("url", [
    "https://www.bilibili.com/video/BV1xx411c7mD",
    "https://www.bilibili.com/video/BV1xx411c7mD?p=3&spm_id_from=333.999",
])
def test_is_bilibili_url_accepts(url):
    assert main.is_bilibili_url(url) is True


@pytest.mark.parametrize("url", [
    "https://example.com/video/abc",
    "https://www.bilibili.com/watchlater/",
    "ftp://www.bilibili.com/video/abc",
    "https://www.bilibili.com/",
    "not a url",
])
def test_is_bilibili_url_rejects(url):
    assert main.is_bilibili_url(url) is False


def test_with_page_append_and_remove():
    from backend.urls import with_page

    base = "https://www.bilibili.com/video/BV1xx"
    assert with_page(base, 1) == base
    assert with_page(base, 2) == base + "?p=2"
    already = base + "?p=2&spm=1"
    assert with_page(already, 3) == base + "?p=3&spm=1"
    assert with_page(already, 1) == base + "?spm=1"