from backend.downloader import _PROBE_CACHE, _probe_season, parse_probe, probe_info


def formats(*qualities):
    f = []
    qn_map = {80: (1080, "hvc1", "1080P 高清", 150 * 1024 * 1024),
              112: (1080, "hvc1", "1080P 高码率", 180 * 1024 * 1024),
              116: (1080, "av01", "1080P 高码率", 90 * 1024 * 1024),
              74: (720, "avc1", "720P 高清", 80 * 1024 * 1024),
              64: (720, "av01", "720P 准高清", 60 * 1024 * 1024),
              32: (480, "avc1", "480P 标清", 40 * 1024 * 1024),
              16: (360, "avc1", "360P 流畅", 20 * 1024 * 1024)}
    for qn in qualities:
        h, vc, name, size = qn_map[qn]
        f.append({"quality": qn, "height": h, "vcodec": f"{vc}." + "1" * 8,
                  "format_id": f"id{qn}", "format": name, "filesize_approx": size})
    return f


def minimal_data(formats_list):
    return {
        "id": "BV1xx411c7mD", "title": "Test Video", "uploader": "Test Uploader",
        "duration": 100,
        "formats": formats_list,
        "pages": [{"id": 1001, "page": 1, "title": "P1"}, {"id": 1002, "page": 2, "title": "P2"}],
    }


class TestParseProbe:
    def test_basic_quality_listing(self):
        data = minimal_data(formats(80, 64, 32))
        out = parse_probe(data, "https://www.bilibili.com/video/BV1xx411c7mD", False)
        labels = [q["label"] for q in out["available_qualities"]]
        assert labels == ["1080P 高清", "720P 准高清", "480P 标清"]
        assert out["auto_resolution"] == "1080P 高清"
        assert out["logged_in"] is False

    def test_multiple_codecs_per_tier_grouped_by_qn(self):
        data = minimal_data(formats(112, 80, 116, 74, 64, 32))
        out = parse_probe(data, "url", True)
        labels = [q["label"] for q in out["available_qualities"]]
        assert labels == ["1080P 高码率", "1080P 高码率", "1080P 高清",
                          "720P 高清", "720P 准高清", "480P 标清"]
        assert out["auto_resolution"] == "1080P 高码率"
        assert out["logged_in"] is True

    def test_codecs_sorted_by_preference(self):
        data = minimal_data(
            [{"quality": 80, "height": 1080, "vcodec": "avc1.640028"},
             {"quality": 80, "height": 1080, "vcodec": "av01.0.08M"},
             {"quality": 80, "height": 1080, "vcodec": "hev1.1.6"}]
        )
        out = parse_probe(data, "url", False)
        assert out["available_qualities"][0]["codecs"] == ["hev1", "av01", "avc1"]

    def test_quality_size_human_readable(self):
        data = minimal_data(formats(80, 32))
        out = parse_probe(data, "url", False)
        sizes = {q["label"]: q["size"] for q in out["available_qualities"]}
        assert len(sizes) == 2
        for label in ("1080P 高清", "480P 标清"):
            v = sizes[label]
            assert v.endswith("MB")
            assert float(v[:-2]) > 0

    def test_without_formats(self):
        out = parse_probe(minimal_data([]), "url", False)
        assert out["available_qualities"] == []

    def test_pages_include_cid_and_title(self):
        out = parse_probe(minimal_data(formats(80)), "url", False)
        assert out["pages"] == [
            {"cid": 1001, "page": 1, "title": "P1"},
            {"cid": 1002, "page": 2, "title": "P2"},
        ]

    def test_season_playlist_maps_episodes_to_pages_with_url(self):
        data = {
            "_type": "playlist",
            "id": "1733",
            "title": "罗小黑战记",
            "entries": [
                {"id": "32374", "title": "1 喵", "webpage_url": "https://www.bilibili.com/bangumi/play/ep32374",
                 "duration": 300, "formats": formats(80, 32)},
                {"id": "32373", "title": "2 逃", "webpage_url": "https://www.bilibili.com/bangumi/play/ep32373",
                 "duration": 300, "formats": formats(80, 32)},
            ],
        }
        out = parse_probe(data, "https://www.bilibili.com/bangumi/play/ss1733", False)
        assert out["bvid"] == "1733"
        assert out["title"] == "罗小黑战记"
        assert out["duration"] == 600
        assert [q["label"] for q in out["available_qualities"]] == ["1080P 高清", "480P 标清"]
        assert out["pages"] == [
            {"cid": "32374", "page": 1, "title": "1 喵",
             "url": "https://www.bilibili.com/bangumi/play/ep32374"},
            {"cid": "32373", "page": 2, "title": "2 逃",
             "url": "https://www.bilibili.com/bangumi/play/ep32373"},
        ]

class TestSeasonProbe:
    def _patch_ydl(self, dispatch):
        from unittest import mock

        class FakeYDL:
            def __init__(self, params=None):
                self.params = params or {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, target, download=False):
                return dispatch(target)

        return mock.patch("backend.downloader.yt_dlp.YoutubeDL", FakeYDL)

    def test_fast_season_probe_builds_pages_and_caches(self, tmp_path):
        from backend.config import Settings

        settings = Settings(tmp_path / "nonexistent.toml")
        _PROBE_CACHE.clear()
        url = "https://www.bilibili.com/bangumi/play/ss1733"
        root = {
            "_type": "playlist",
            "title": "罗小黑战记",
            "entries": [
                {"id": "32374"},
                {"id": "32373"},
            ],
        }
        sample = {"id": "32374", "formats": formats(80, 32)}

        def dispatch(target):
            return root if str(target) == url else sample

        with self._patch_ydl(dispatch):
            info = probe_info(settings, url)
        assert info["title"] == "罗小黑战记"
        assert len(info["pages"]) == 2
        assert info["pages"][0]["url"] == "https://www.bilibili.com/bangumi/play/ep32374"
        # flat entries carry no title, so the fallback label is the plain EP number
        assert info["pages"][0]["title"] == "EP 1"
        assert [q["label"] for q in info["available_qualities"]] == ["1080P 高清", "480P 标清"]
        assert (url, False) in _PROBE_CACHE
        # cached revisit must not hit yt-dlp again
        calls = []

        def dispatch2(target):
            calls.append(str(target))
            return sample

        with self._patch_ydl(dispatch2):
            info2 = probe_info(settings, url)
        assert info2 == info
        assert calls == []

    def test_probe_season_builds_ep_urls_and_fallback_titles(self, tmp_path):
        from unittest import mock

        from backend.config import Settings

        settings = Settings(tmp_path / "nonexistent.toml")
        url = "https://www.bilibili.com/bangumi/play/ss1733"

        with mock.patch("backend.downloader.yt_dlp.YoutubeDL") as ydl:
            ydl.return_value.extract_info.side_effect = [
                {"_type": "playlist", "entries": [{"id": "32374"}, {"id": "32373"}]},
                {"id": "32374", "formats": formats(80, 32)},
            ]
            ydl.return_value.__enter__.return_value = ydl.return_value
            root = _probe_season(settings, url, {})
        assert root["entries"][0]["title"] == "EP 1"
        assert root["entries"][1]["title"] == "EP 2"
        assert root["entries"][0]["webpage_url"] == "https://www.bilibili.com/bangumi/play/ep32374"
        assert root["formats"]
