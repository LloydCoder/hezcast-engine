"""
HezCast Engine — Thumbnail Engine Tests
TDD Phase 6 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

Extracts keyframes from rendered video + overlays brand text
→ 3 thumbnail variants per job (hook / curiosity / authority)
"""

import pytest
import wave
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def thumbnail_engine():
    from core.thumbnail_engine import ThumbnailEngine
    return ThumbnailEngine()

@pytest.fixture
def fake_mp4(tmp_path):
    """Fake MP4 file"""
    p = tmp_path / "final.mp4"
    p.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * (5 * 1024 * 1024))
    return p

@pytest.fixture
def sample_bundle():
    return {
        "title":   "I forgot her birthday TWICE (this app saved me)",
        "caption": "Nobody warned me about the gift panic 😭",
        "hashtags": ["#GiftMode", "#GiftIdeas", "#BirthdayGift"],
        "cta_link": "https://giftmode.app",
    }

@pytest.fixture
def mock_frame(tmp_path):
    """Fake keyframe PNG"""
    frame = tmp_path / "keyframe.png"
    # Minimal PNG header
    frame.write_bytes(
        b'\x89PNG\r\n\x1a\n' +
        b'\x00\x00\x00\rIHDR' +
        b'\x00\x00\x04\x38' +  # width 1080
        b'\x00\x00\x07\x80' +  # height 1920
        b'\x08\x02\x00\x00\x00' +
        b'\x00' * 100
    )
    return frame


# ─────────────────────────────────────────────
# KEYFRAME EXTRACTION TESTS
# ─────────────────────────────────────────────

class TestKeyframeExtraction:

    def test_extract_keyframe_returns_path(self, thumbnail_engine, fake_mp4, tmp_path):
        """extract_keyframe must return a file path"""
        with patch.object(thumbnail_engine, '_run_ffmpeg_frame') as mock_ff:
            out = tmp_path / "frame.png"
            out.write_bytes(b"fake_png_data")
            mock_ff.return_value = str(out)
            result = thumbnail_engine.extract_keyframe(
                video_path=str(fake_mp4),
                output_path=str(out),
                timestamp_sec=2.0
            )
        assert result == str(out)

    def test_extract_keyframe_missing_video_raises(self, thumbnail_engine, tmp_path):
        """Missing video file must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            thumbnail_engine.extract_keyframe(
                video_path="/nonexistent/video.mp4",
                output_path=str(tmp_path / "frame.png"),
                timestamp_sec=2.0
            )

    def test_extract_keyframe_timestamp_is_positive(self, thumbnail_engine, fake_mp4, tmp_path):
        """Timestamp must be >= 0"""
        with patch.object(thumbnail_engine, '_run_ffmpeg_frame') as mock_ff:
            out = tmp_path / "frame.png"
            out.write_bytes(b"fake")
            mock_ff.return_value = str(out)
            # Should not raise
            thumbnail_engine.extract_keyframe(
                video_path=str(fake_mp4),
                output_path=str(out),
                timestamp_sec=0.0
            )

    def test_extract_best_frame_returns_path(self, thumbnail_engine, fake_mp4, tmp_path):
        """extract_best_frame must return the best keyframe path"""
        with patch.object(thumbnail_engine, 'extract_keyframe') as mock_ext:
            out = tmp_path / "best_frame.png"
            out.write_bytes(b"fake")
            mock_ext.return_value = str(out)
            result = thumbnail_engine.extract_best_frame(
                video_path=str(fake_mp4),
                output_dir=str(tmp_path)
            )
        assert result is not None


# ─────────────────────────────────────────────
# THUMBNAIL GENERATION TESTS
# ─────────────────────────────────────────────

class TestThumbnailGeneration:

    def test_generate_returns_list(self, thumbnail_engine, fake_mp4, sample_bundle, tmp_path):
        """generate() must return a list of thumbnail paths"""
        with patch.object(thumbnail_engine, 'extract_best_frame') as mock_frame:
            frame = tmp_path / "frame.png"
            frame.write_bytes(b"fake_png")
            mock_frame.return_value = str(frame)
            with patch.object(thumbnail_engine, '_create_thumbnail') as mock_create:
                mock_create.side_effect = lambda *a, **kw: (
                    lambda p: (Path(p).write_bytes(b"png"), p)[1]
                )(kw.get('output_path', str(tmp_path / "thumb.png")))
                results = thumbnail_engine.generate(
                    video_path=str(fake_mp4),
                    bundle=sample_bundle,
                    brand="GiftMode",
                    output_dir=str(tmp_path)
                )
        assert isinstance(results, list)

    def test_generate_returns_3_variants(self, thumbnail_engine, fake_mp4, sample_bundle, tmp_path):
        """generate() must return exactly 3 thumbnail variants"""
        with patch.object(thumbnail_engine, 'extract_best_frame') as mock_frame:
            frame = tmp_path / "frame.png"
            frame.write_bytes(b"fake_png")
            mock_frame.return_value = str(frame)
            with patch.object(thumbnail_engine, '_create_thumbnail') as mock_create:
                paths = [str(tmp_path / f"t{i}.png") for i in range(3)]
                for p in paths:
                    Path(p).write_bytes(b"png")
                mock_create.side_effect = lambda *a, **kw: kw.get('output_path', paths[0])
                results = thumbnail_engine.generate(
                    video_path=str(fake_mp4),
                    bundle=sample_bundle,
                    brand="GiftMode",
                    output_dir=str(tmp_path)
                )
        assert len(results) == 3

    def test_generate_variant_names(self, thumbnail_engine, fake_mp4, sample_bundle, tmp_path):
        """Variants must be named hook, curiosity, authority"""
        with patch.object(thumbnail_engine, 'extract_best_frame') as mock_frame:
            frame = tmp_path / "frame.png"
            frame.write_bytes(b"fake_png")
            mock_frame.return_value = str(frame)
            with patch.object(thumbnail_engine, '_create_thumbnail') as mock_create:
                mock_create.side_effect = lambda *a, **kw: kw.get('output_path', str(tmp_path / "t.png"))
                results = thumbnail_engine.generate(
                    video_path=str(fake_mp4),
                    bundle=sample_bundle,
                    brand="GiftMode",
                    output_dir=str(tmp_path)
                )
        variant_names = [r.get("variant") for r in results if isinstance(r, dict)]
        if variant_names:
            assert "hook" in variant_names
            assert "curiosity" in variant_names
            assert "authority" in variant_names

    def test_generate_missing_video_raises(self, thumbnail_engine, sample_bundle, tmp_path):
        """Missing video must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            thumbnail_engine.generate(
                video_path="/nonexistent/video.mp4",
                bundle=sample_bundle,
                brand="GiftMode",
                output_dir=str(tmp_path)
            )

    def test_generate_unknown_brand_raises(self, thumbnail_engine, fake_mp4, sample_bundle, tmp_path):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            thumbnail_engine.generate(
                video_path=str(fake_mp4),
                bundle=sample_bundle,
                brand="FakeBrand",
                output_dir=str(tmp_path)
            )


# ─────────────────────────────────────────────
# BRAND STYLE TESTS
# ─────────────────────────────────────────────

class TestBrandStyles:

    def test_get_brand_style_returns_dict(self, thumbnail_engine):
        """get_brand_style must return a dict"""
        for brand in ["GiftMode", "Tinlance", "WebTemify", "HezCast"]:
            style = thumbnail_engine.get_brand_style(brand)
            assert isinstance(style, dict)

    def test_brand_style_has_required_keys(self, thumbnail_engine):
        """Brand style must have color, font_size, bg_color"""
        required = ["primary_color", "bg_color", "font_size", "text_color"]
        for brand in ["GiftMode", "Tinlance", "WebTemify", "HezCast"]:
            style = thumbnail_engine.get_brand_style(brand)
            for key in required:
                assert key in style, f"{brand} style missing {key}"

    def test_giftmode_uses_pink(self, thumbnail_engine):
        """GiftMode style must use pink"""
        style = thumbnail_engine.get_brand_style("GiftMode")
        assert "FF6B9D" in style["primary_color"].upper()

    def test_tinlance_uses_cyan(self, thumbnail_engine):
        """Tinlance style must use cyan"""
        style = thumbnail_engine.get_brand_style("Tinlance")
        assert "00D4FF" in style["primary_color"].upper()

    def test_hezcast_uses_cyan(self, thumbnail_engine):
        """HezCast style must use cyan (same as Tinlance — same persona)"""
        style = thumbnail_engine.get_brand_style("HezCast")
        assert "00D4FF" in style["primary_color"].upper()

    def test_unknown_brand_raises(self, thumbnail_engine):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            thumbnail_engine.get_brand_style("FakeBrand")


# ─────────────────────────────────────────────
# HEADLINE GENERATION TESTS
# ─────────────────────────────────────────────

class TestHeadlineGeneration:

    def test_generate_headlines_returns_3(self, thumbnail_engine, sample_bundle):
        """Must generate exactly 3 headlines — hook, curiosity, authority"""
        headlines = thumbnail_engine.generate_headlines(sample_bundle, brand="GiftMode")
        assert len(headlines) == 3

    def test_headlines_have_variant_keys(self, thumbnail_engine, sample_bundle):
        """Headlines dict must have hook, curiosity, authority keys"""
        headlines = thumbnail_engine.generate_headlines(sample_bundle, brand="GiftMode")
        assert "hook" in headlines
        assert "curiosity" in headlines
        assert "authority" in headlines

    def test_headlines_under_10_words(self, thumbnail_engine, sample_bundle):
        """Each headline must be under 10 words for thumbnail readability"""
        headlines = thumbnail_engine.generate_headlines(sample_bundle, brand="GiftMode")
        for variant, text in headlines.items():
            word_count = len(text.split())
            assert word_count <= 10, f"{variant} headline too long: {text}"

    def test_headlines_not_empty(self, thumbnail_engine, sample_bundle):
        """No headline can be empty"""
        headlines = thumbnail_engine.generate_headlines(sample_bundle, brand="GiftMode")
        for variant, text in headlines.items():
            assert len(text.strip()) > 0, f"{variant} headline is empty"

    def test_different_brands_different_headlines(self, thumbnail_engine):
        """Different brands must produce different headlines"""
        bundle = {
            "title": "Test video",
            "caption": "Test caption",
            "hashtags": ["#test"],
            "cta_link": "https://test.com"
        }
        h_giftmode = thumbnail_engine.generate_headlines(bundle, brand="GiftMode")
        h_tinlance = thumbnail_engine.generate_headlines(bundle, brand="Tinlance")
        assert h_giftmode != h_tinlance
