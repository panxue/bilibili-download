import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

_BANGUMI_PLAY = re.compile(r"/bangumi/play/(ss|ep)[0-9]+/?$")


def is_bilibili_url(url: str) -> bool:
    """Accept bilibili video pages and bangumi play pages (season ss / episode ep)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or "bilibili.com" not in parts.netloc:
        return False
    return "video/" in parts.path or bool(_BANGUMI_PLAY.search(parts.path))


def is_bangumi_season(url: str) -> bool:
    """True for a bangumi season URL (/bangumi/play/ss1234); ep links are single episodes."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return bool(re.search(r"/bangumi/play/ss[0-9]+/?$", parts.path))


def with_page(url: str, page: int) -> str:
    """Point a multi-part video URL at the given part (?p=N)."""
    parts = urlsplit(url)
    q = {k: v for k, v in parse_qs(parts.query).items()}
    if page and page > 1:
        q["p"] = [str(page)]
    else:
        q.pop("p", None)
    parts = parts._replace(query=urlencode(q, doseq=True))
    return urlunsplit(parts)