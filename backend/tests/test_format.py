from backend.downloader import (
    _FORMAT_TABLE,
    JobState,
    _download_format,
    bind_qualities,
    quality_to_format,
)


def make_fmt(cond: str, codec: str) -> str:
    return f"bestvideo{cond}[vcodec*={codec}]+bestaudio"


class TestQualityToFormat:
    def test_auto_no_height_limit_default_order(self):
        expected = (
            "bestvideo[vcodec*=hev1]+bestaudio/bestvideo[vcodec*=hvc1]+bestaudio/"
            "bestvideo[vcodec*=av01]+bestaudio/bestvideo[vcodec*=avc1]+bestaudio/"
            "bestvideo+bestaudio/best"
        )
        assert quality_to_format("auto") == expected
        assert quality_to_format("auto", "") == expected

    def test_named_qualities_map_to_heights(self):
        assert "height<=4320" in quality_to_format("8K")
        assert "height<=2160" in quality_to_format("4K")
        assert "height<=1440" in quality_to_format("2K")
        assert "height<=1080" in quality_to_format("1080P")
        assert "height<=1080" in quality_to_format("1080P60")
        assert "height<=720" in quality_to_format("720P")
        assert "height<=720" in quality_to_format("720P60")
        assert "height<=480" in quality_to_format("480P")
        assert "height<=360" in quality_to_format("360P")

    def test_arbitrary_p_quality(self):
        fmt = quality_to_format("820P")
        assert "height<=820" in fmt

    def test_audio_returns_bestaudio(self):
        assert quality_to_format("audio") == "bestaudio"

    def test_unknown_quality_falls_back_to_no_limit(self):
        fmt = quality_to_format("SPA")
        assert "height<=" not in fmt
        assert quality_to_format("SPA") == quality_to_format("auto")

    def test_codec_order_injected(self):
        fmt = quality_to_format("1080P", "avc1,hev1")
        assert fmt.startswith(make_fmt("[height<=1080]", "avc1"))
        assert "[vcodec*=hev1]" in fmt
        assert "[vcodec*=av01]" in fmt

    def test_codec_auto_ignores_explicit(self):
        assert quality_to_format("auto", "avc")[0:0] == ""


def quality_entry(fid, fam, height=1080, label="1080P 高清"):
    return {"qn": 80, "label": label, "height": height,
            "codecs": [fam], "format_ids": {fam: fid}, "size": "1.0 MB"}


class TestBindQualities:
    def setup_method(self):
        _FORMAT_TABLE.clear()

    def test_binds_one_format_id_per_tier(self):
        qs = [quality_entry("100035", "avc1"), quality_entry("100036", "hev1")]
        out = bind_qualities(qs, "auto")
        assert [q["format_id"] for q in out] == ["100035", "100036"]
        assert all(q["codec"] in ("avc1", "hev1") for q in out)
        assert out[0]["label"] == "1080P 高清"

    def test_codec_preference_selects_family(self):
        mixed = {"qn": 80, "label": "1080P 高清", "height": 1080,
                 "codecs": ["avc1", "hev1"], "format_ids": {"avc1": "100035", "hev1": "100036"},
                 "size": "1.0 MB"}
        out = bind_qualities([mixed], "auto")
        assert out[0]["format_id"] == "100036"  # default hev1 > hvc1 > av01 > avc1
        assert _FORMAT_TABLE["100036"].startswith("bestvideo[height<=1080][vcodec*=hev1]")
        out2 = bind_qualities([mixed], "avc1,hev1,hvc1")
        assert out2[0]["format_id"] == "100035"
        assert out2[0]["codec"] == "avc1"

    def test_table_records_height_codec_fallback(self):
        bind_qualities([quality_entry("100036", "hev1", height=2160, label="4K 超高清")], "auto")
        assert _FORMAT_TABLE.get("100036") == "bestvideo[height<=2160][vcodec*=hev1]+bestaudio"


def make_state(params, quality="1080P"):
    return JobState(id="x", url="https://www.bilibili.com/video/BV1xx411c7mD", bvid="BV1xx411c7mD",
                    page=1, title="t", quality=quality, params=params)


class TestDownloadFormat:
    def test_format_id_uses_bestaudio_plus_fallback(self):
        state = make_state({"format_id": "100036", "format_fallback": "bestvideo[height<=2160][vcodec*=hev1]+bestaudio"})
        assert _download_format(state) == "100036+bestaudio/bestvideo[height<=2160][vcodec*=hev1]+bestaudio/best"

    def test_format_id_without_fallback_defaults_to_best(self):
        state = make_state({"format_id": "100036"})
        assert _download_format(state) == "100036+bestaudio/best"

    def test_audio_request_ignores_format_id(self):
        state = make_state({"format_id": "100036"}, quality="audio")
        assert _download_format(state) == "bestaudio"

    def test_no_format_id_uses_legacy_mapping(self):
        state = make_state({}, quality="1080P")
        assert _download_format(state) == quality_to_format("1080P", "auto")

    def test_no_format_id_uses_codec_param(self):
        state = make_state({"codec": "avc1,hev1"}, quality="720P")
        assert _download_format(state) == quality_to_format("720P", "avc1,hev1")