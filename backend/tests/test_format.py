from backend.downloader import quality_to_format


def make_fmt(cond: str, codec: str) -> str:
    return f"bestvideo{cond}[vcodec*={codec}]+bestaudio"


class TestQualityToFormat:
    def test_auto_no_height_limit_default_order(self):
        expected = (
            "bestvideo[vcodec*=hvc]+bestaudio/bestvideo[vcodec*=av01]+bestaudio/"
            "bestvideo[vcodec*=avc]+bestaudio/bestvideo+bestaudio/best"
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
        fmt = quality_to_format("1080P", "avc,hvc")
        assert fmt.startswith(make_fmt("[height<=1080]", "avc"))
        assert "[vcodec*=hvc]" in fmt
        assert "[vcodec*=av01]" in fmt

    def test_codec_auto_ignores_explicit(self):
        assert quality_to_format("auto", "avc")[0:0] == ""