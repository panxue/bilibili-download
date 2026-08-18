from backend.downloader import codec_family, codec_rank, normalize_codec_order


class TestNormalizeCodecOrder:
    def test_auto_and_empty_use_default(self):
        assert normalize_codec_order("") == ["hvc", "av01", "avc"]
        assert normalize_codec_order("auto") == ["hvc", "av01", "avc"]
        assert normalize_codec_order("Auto") == ["hvc", "av01", "avc"]
        assert normalize_codec_order(None) == ["hvc", "av01", "avc"]

    def test_explicit_order_preserved(self):
        assert normalize_codec_order("avc,hvc,av01") == ["avc", "hvc", "av01"]
        assert normalize_codec_order("av01,hvc") == ["av01", "hvc", "avc"]

    def test_spaces_and_unknown_items_ignored(self):
        assert normalize_codec_order(" hvc , foo , avc ") == ["hvc", "avc", "av01"]
        assert normalize_codec_order("foo,bar") == ["hvc", "av01", "avc"]

    def test_alias_hev1_maps_to_hvc(self):
        assert normalize_codec_order("hev1,avc") == ["hvc", "avc", "av01"]

    def test_untouched_families_appended(self):
        assert normalize_codec_order("hvc") == ["hvc", "av01", "avc"]
        assert normalize_codec_order("avc") == ["avc", "hvc", "av01"]


class TestCodecFamily:
    def test_known_families(self):
        assert codec_family("hvc1.1.6.L150.90") == "hvc"
        assert codec_family("hev1.1.6") == "hvc"
        assert codec_family("av01.0.08M.08") == "av01"
        assert codec_family("avc1.640028") == "avc"

    def test_unknown_and_empty(self):
        assert codec_family("vp09.00.10") == "vp09"
        assert codec_family("") == "unknown"
        assert codec_family(None) == "unknown"


class TestCodecRank:
    def test_order(self):
        assert codec_rank("hvc") == 0
        assert codec_rank("av01") == 1
        assert codec_rank("avc") == 2

    def test_unknown_rank_lowest(self):
        assert codec_rank("vp09") == 99
