from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def is_bilibili_url(url: str) -> bool:
    """Accept only bilibili video page URLs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and (
        "bilibili.com" in parts.netloc and "video/" in parts.path
    )


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