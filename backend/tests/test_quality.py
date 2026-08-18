from backend.downloader import parse_probe


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