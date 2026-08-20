from backend.downloader import _PROBE_CACHE, _probe_season, parse_probe, probe_info


def formats(*qualities):
    f = []
    qn_map = {80: (1080, "hvc1"), 112: (1080, "hvc1"), 116: (1080, "av01"),
              74: (720, "avc1"), 64: (720, "av01"), 32: (480, "avc1"), 16: (360, "avc1")}
    for qn in qualities:
        h, vc = qn_map[qn]
        f.append({"quality": qn, "height": h, "vcodec": f"{vc}." + "1" * 8})
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
        assert labels == ["1080P", "720P", "480P"]
        assert out["auto_resolution"] == "1080P"
        assert out["logged_in"] is False

    def test_high_fps_and_higher_tiers_separated_by_qn(self):
        data = minimal_data(formats(112, 80, 116, 74, 64, 32))
        out = parse_probe(data, "url", True)
        labels = [q["label"] for q in out["available_qualities"]]
        assert labels == ["1080P60", "1080P60", "1080P", "720P60", "720P", "480P"]
        assert out["auto_resolution"] == "1080P60"
        assert out["logged_in"] is True

    def test_codecs_sorted_by_preference(self):
        data = minimal_data(
            [{"quality": 80, "height": 1080, "vcodec": "avc1.640028"},
             {"quality": 80, "height": 1080, "vcodec": "av01.0.08M"},
             {"quality": 80, "height": 1080, "vcodec": "hev1.1.6"}]
        )
        out = parse_probe(data, "url", False)
        assert out["available_qualities"][0]["codecs"] == ["hvc", "av01", "avc"]

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
        assert [q["label"] for q in out["available_qualities"]] == ["1080P", "480P"]
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
        assert [q["label"] for q in info["available_qualities"]] == ["1080P", "480P"]
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
