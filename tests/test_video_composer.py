"""
HezCast Engine — Video Composer Tests
TDD Phase 3 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

FFmpeg orchestration:
  background_clip + avatar_overlay + subtitles + brand_lower_third → MP4
"""

import pytest
import os
import json
import wave
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def composer():
    from core.video_composer import VideoComposer
    return VideoComposer()

@pytest.fixture
def sample_wav(tmp_path):
    """Valid 5-second WAV file"""
    path = tmp_path / "voice.wav"
    sample_rate = 22050
    duration = 5
    num_frames = sample_rate * duration
    with wave.open(str(path), 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(struct.pack('<' + 'h' * num_frames, *([100] * num_frames)))
    return path

@pytest.fixture
def sample_compose_request(tmp_path, sample_wav):
    """Full compose request dict"""
    # Create fake input files
    bg_clip = tmp_path / "background.mp4"
    bg_clip.write_bytes(b"fake_mp4_data")
    subtitle_file = tmp_path / "subtitles.ass"
    subtitle_file.write_text("[Script Info]\nTitle: Test\n")

    return {
        "job_id":        "test-job-abc123",
        "brand":         "GiftMode",
        "voice_path":    str(sample_wav),
        "bg_clip_path":  str(bg_clip),
        "subtitle_path": str(subtitle_file),
        "output_path":   str(tmp_path / "output.mp4"),
        "duration_sec":  25.0,
    }

def _make_fake_mp4(path: Path, size_bytes: int = 1024) -> Path:
    """Create a fake MP4 file for testing"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * (size_bytes - 12))
    return path


# ─────────────────────────────────────────────
# COMPOSE REQUEST VALIDATION TESTS
# ─────────────────────────────────────────────

class TestComposeRequestValidation:

    def test_valid_request_passes_validation(self, composer, sample_compose_request):
        """Valid compose request must not raise"""
        try:
            composer._validate_compose_request(sample_compose_request)
        except Exception as e:
            pytest.fail(f"Valid request raised: {e}")

    def test_missing_job_id_raises(self, composer, sample_compose_request):
        """Missing job_id must raise ValueError"""
        del sample_compose_request["job_id"]
        with pytest.raises(ValueError, match="job_id"):
            composer._validate_compose_request(sample_compose_request)

    def test_missing_brand_raises(self, composer, sample_compose_request):
        """Missing brand must raise ValueError"""
        del sample_compose_request["brand"]
        with pytest.raises(ValueError, match="brand"):
            composer._validate_compose_request(sample_compose_request)

    def test_unknown_brand_raises(self, composer, sample_compose_request):
        """Unknown brand must raise ValueError"""
        sample_compose_request["brand"] = "FakeBrand"
        with pytest.raises(ValueError, match="Unknown brand"):
            composer._validate_compose_request(sample_compose_request)

    def test_missing_voice_path_raises(self, composer, sample_compose_request):
        """Missing voice_path must raise ValueError"""
        del sample_compose_request["voice_path"]
        with pytest.raises(ValueError, match="voice_path"):
            composer._validate_compose_request(sample_compose_request)

    def test_nonexistent_voice_file_raises(self, composer, sample_compose_request):
        """Non-existent voice file must raise FileNotFoundError"""
        sample_compose_request["voice_path"] = "/nonexistent/voice.wav"
        with pytest.raises(FileNotFoundError, match="voice"):
            composer._validate_compose_request(sample_compose_request)

    def test_missing_output_path_raises(self, composer, sample_compose_request):
        """Missing output_path must raise ValueError"""
        del sample_compose_request["output_path"]
        with pytest.raises(ValueError, match="output_path"):
            composer._validate_compose_request(sample_compose_request)

    def test_invalid_duration_raises(self, composer, sample_compose_request):
        """duration_sec <= 0 must raise ValueError"""
        sample_compose_request["duration_sec"] = -5.0
        with pytest.raises(ValueError, match="duration"):
            composer._validate_compose_request(sample_compose_request)

    def test_zero_duration_raises(self, composer, sample_compose_request):
        """duration_sec = 0 must raise ValueError"""
        sample_compose_request["duration_sec"] = 0
        with pytest.raises(ValueError, match="duration"):
            composer._validate_compose_request(sample_compose_request)


# ─────────────────────────────────────────────
# FFMPEG COMMAND BUILDER TESTS
# ─────────────────────────────────────────────

class TestFFmpegCommandBuilder:

    def test_build_command_returns_list(self, composer, sample_compose_request):
        """_build_ffmpeg_cmd must return a list"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        assert isinstance(cmd, list)

    def test_command_starts_with_ffmpeg(self, composer, sample_compose_request):
        """Command must start with ffmpeg binary"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        assert cmd[0] == "ffmpeg"

    def test_command_includes_voice_input(self, composer, sample_compose_request):
        """Command must reference the voice WAV file"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        cmd_str = " ".join(cmd)
        assert sample_compose_request["voice_path"] in cmd_str

    def test_command_includes_output_path(self, composer, sample_compose_request):
        """Command must reference the output path"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        assert sample_compose_request["output_path"] in cmd

    def test_command_specifies_vertical_resolution(self, composer, sample_compose_request):
        """Command must specify 1080x1920 (9:16 vertical)"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        cmd_str = " ".join(cmd)
        assert "1080" in cmd_str and "1920" in cmd_str

    def test_command_specifies_h264_codec(self, composer, sample_compose_request):
        """Command must use H.264 video codec"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        cmd_str = " ".join(cmd)
        assert "libx264" in cmd_str

    def test_command_specifies_aac_audio(self, composer, sample_compose_request):
        """Command must use AAC audio codec"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        cmd_str = " ".join(cmd)
        assert "aac" in cmd_str

    def test_command_includes_overwrite_flag(self, composer, sample_compose_request):
        """Command must include -y flag to overwrite existing output"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        assert "-y" in cmd

    def test_command_includes_subtitle_when_provided(self, composer, sample_compose_request):
        """Command must include subtitle file when provided"""
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        cmd_str = " ".join(cmd)
        assert sample_compose_request["subtitle_path"] in cmd_str

    def test_command_works_without_subtitle(self, composer, sample_compose_request):
        """Command must still build when no subtitle_path provided"""
        del sample_compose_request["subtitle_path"]
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        assert isinstance(cmd, list)
        assert "ffmpeg" in cmd[0]

    def test_command_works_without_bg_clip(self, composer, sample_compose_request):
        """Command must still build when no bg_clip_path (uses color background)"""
        del sample_compose_request["bg_clip_path"]
        cmd = composer._build_ffmpeg_cmd(sample_compose_request)
        assert isinstance(cmd, list)
        # Should use a solid color background instead
        cmd_str = " ".join(cmd)
        assert "color" in cmd_str.lower() or "lavfi" in cmd_str.lower()


# ─────────────────────────────────────────────
# COMPOSE PIPELINE TESTS
# ─────────────────────────────────────────────

class TestComposePipeline:

    def test_compose_returns_output_path(self, composer, sample_compose_request, tmp_path):
        """compose() must return the output path string"""
        with patch.object(composer, '_run_ffmpeg') as mock_ffmpeg:
            mock_ffmpeg.side_effect = lambda cmd, out: _make_fake_mp4(Path(out))
            result = composer.compose(sample_compose_request)
        assert result == sample_compose_request["output_path"]

    def test_compose_calls_run_ffmpeg_once(self, composer, sample_compose_request):
        """compose() must call _run_ffmpeg exactly once"""
        with patch.object(composer, '_run_ffmpeg') as mock_ffmpeg:
            mock_ffmpeg.side_effect = lambda cmd, out: _make_fake_mp4(
                Path(sample_compose_request["output_path"])
            )
            composer.compose(sample_compose_request)
        assert mock_ffmpeg.call_count == 1

    def test_compose_creates_output_file(self, composer, sample_compose_request):
        """compose() must create the output file"""
        out_path = Path(sample_compose_request["output_path"])
        with patch.object(composer, '_run_ffmpeg') as mock_ffmpeg:
            mock_ffmpeg.side_effect = lambda cmd, out: _make_fake_mp4(Path(out))
            composer.compose(sample_compose_request)
        assert out_path.exists()

    def test_compose_raises_on_ffmpeg_failure(self, composer, sample_compose_request):
        """compose() must raise VideoComposeError when FFmpeg fails"""
        from core.video_composer import VideoComposeError
        with patch.object(composer, '_run_ffmpeg', side_effect=VideoComposeError("FFmpeg failed")):
            with pytest.raises(VideoComposeError):
                composer.compose(sample_compose_request)

    def test_compose_validates_request_first(self, composer, sample_compose_request):
        """compose() must validate request before calling FFmpeg"""
        sample_compose_request["brand"] = "FakeBrand"
        with patch.object(composer, '_run_ffmpeg') as mock_ffmpeg:
            with pytest.raises(ValueError, match="Unknown brand"):
                composer.compose(sample_compose_request)
        assert mock_ffmpeg.call_count == 0

    def test_compose_creates_output_directory(self, composer, sample_compose_request, tmp_path):
        """compose() must create output directory if it doesn't exist"""
        deep_path = tmp_path / "deep" / "nested" / "output.mp4"
        sample_compose_request["output_path"] = str(deep_path)
        with patch.object(composer, '_run_ffmpeg') as mock_ffmpeg:
            mock_ffmpeg.side_effect = lambda cmd, out: _make_fake_mp4(Path(out))
            composer.compose(sample_compose_request)
        assert deep_path.parent.exists()


# ─────────────────────────────────────────────
# BRAND OVERLAY TESTS
# ─────────────────────────────────────────────

class TestBrandOverlay:

    def test_get_brand_overlay_returns_dict(self, composer):
        """get_brand_overlay must return a dict"""
        overlay = composer.get_brand_overlay("GiftMode")
        assert isinstance(overlay, dict)

    def test_brand_overlay_has_required_keys(self, composer):
        """Brand overlay must have color, cta_text, subtitle_color"""
        required = ["primary_color", "subtitle_color", "cta_text"]
        for brand in ["GiftMode", "Tinlance", "WebTemify"]:
            overlay = composer.get_brand_overlay(brand)
            for key in required:
                assert key in overlay, f"{brand} overlay missing: {key}"

    def test_giftmode_overlay_uses_pink(self, composer):
        """GiftMode overlay must use pink brand color"""
        overlay = composer.get_brand_overlay("GiftMode")
        assert "#FF6B9D" in overlay["primary_color"] or \
               "FF6B9D" in overlay["primary_color"].upper()

    def test_tinlance_overlay_uses_cyan(self, composer):
        """Tinlance overlay must use cyan brand color"""
        overlay = composer.get_brand_overlay("Tinlance")
        assert "00D4FF" in overlay["primary_color"].upper() or \
               "00d4ff" in overlay["primary_color"].lower()

    def test_webtemify_overlay_uses_violet(self, composer):
        """WebTemify overlay must use violet brand color"""
        overlay = composer.get_brand_overlay("WebTemify")
        assert "7C3AED" in overlay["primary_color"].upper() or \
               "7c3aed" in overlay["primary_color"].lower()

    def test_unknown_brand_raises(self, composer):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            composer.get_brand_overlay("FakeBrand")

    def test_all_brands_have_distinct_colors(self, composer):
        """Each brand must have a unique primary color"""
        colors = [
            composer.get_brand_overlay(b)["primary_color"]
            for b in ["GiftMode", "Tinlance", "WebTemify"]
        ]
        assert len(set(colors)) == 3, "Brand overlay colors are not unique"
