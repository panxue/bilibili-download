from backend.downloader import codec_family, codec_rank, normalize_codec_order


class TestNormalizeCodecOrder:
    def test_auto_and_empty_use_default(self):
        assert normalize_codec_order("") == ["hev1", "hvc1", "av01", "avc1"]
        assert normalize_codec_order("auto") == ["hev1", "hvc1", "av01", "avc1"]
        assert normalize_codec_order("Auto") == ["hev1", "hvc1", "av01", "avc1"]
        assert normalize_codec_order(None) == ["hev1", "hvc1", "av01", "avc1"]

    def test_explicit_order_preserved(self):
        assert normalize_codec_order("avc1,hev1,hvc1,av01") == ["avc1", "hev1", "hvc1", "av01"]
        assert normalize_codec_order("av01,hev1") == ["av01", "hev1", "hvc1", "avc1"]

    def test_spaces_and_unknown_items_ignored(self):
        assert normalize_codec_order(" hvc1 , foo , avc1 ") == ["hvc1", "avc1", "hev1", "av01"]
        assert normalize_codec_order("foo,bar") == ["hev1", "hvc1", "av01", "avc1"]

    def test_untouched_prefixes_appended(self):
        assert normalize_codec_order("hvc1") == ["hvc1", "hev1", "av01", "avc1"]
        assert normalize_codec_order("avc1") == ["avc1", "hev1", "hvc1", "av01"]


class TestCodecFamily:
    def test_known_prefixes(self):
        assert codec_family("hvc1.1.6.L150.90") == "hvc1"
        assert codec_family("hev1.1.6") == "hev1"
        assert codec_family("av01.0.08M.08") == "av01"
        assert codec_family("avc1.640028") == "avc1"

    def test_unknown_and_empty(self):
        assert codec_family("vp09.00.10") == "vp09"
        assert codec_family("") == "unknown"
        assert codec_family(None) == "unknown"


class TestCodecRank:
    def test_order(self):
        assert codec_rank("hev1") == 0
        assert codec_rank("hvc1") == 1
        assert codec_rank("av01") == 2
        assert codec_rank("avc1") == 3

    def test_unknown_rank_lowest(self):
        assert codec_rank("vp09") == 99
