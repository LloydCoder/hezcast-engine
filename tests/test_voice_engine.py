"""
HezCast Engine — Voice Engine Tests
TDD Phase 2 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)
"""

import pytest
import wave
import struct
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def voice_engine():
    from core.voice_engine import VoiceEngine
    return VoiceEngine()

@pytest.fixture
def sample_script():
    return (
        "Nobody told me you could forget your mum's birthday TWICE. "
        "I had 2 hours, zero ideas, and a guilt trip loading. "
        "GiftMode gave me 3 perfect ideas in 9 seconds. Done. "
        "Download GiftMode. Before you forget again."
    )

@pytest.fixture
def output_path(tmp_path):
    return tmp_path / "test_voice.wav"

def _make_wav(path: Path, duration_sec: float = 2.0, sample_rate: int = 22050) -> Path:
    """Create a valid WAV file for testing"""
    num_frames = int(sample_rate * duration_sec)
    with wave.open(str(path), 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        frames = struct.pack('<' + 'h' * num_frames, *([100] * num_frames))
        f.writeframes(frames)
    return path


# ─────────────────────────────────────────────
# BRAND VOICE PROFILE TESTS
# ─────────────────────────────────────────────

class TestBrandVoiceProfiles:

    def test_all_brands_have_voice_config(self, voice_engine):
        """Every brand must have a voice profile"""
        for brand in ["GiftMode", "Tinlance", "WebTemify"]:
            profile = voice_engine.get_voice_profile(brand)
            assert profile is not None, f"No voice profile for {brand}"

    def test_voice_profile_has_required_keys(self, voice_engine):
        """Each voice profile must have all required fields"""
        required = ["speed", "sample_rate", "model_id", "description"]
        for brand in ["GiftMode", "Tinlance", "WebTemify"]:
            profile = voice_engine.get_voice_profile(brand)
            for key in required:
                assert key in profile, f"{brand} voice profile missing: {key}"

    def test_giftmode_voice_is_faster(self, voice_engine):
        """GiftMode voice should be faster than Tinlance (UGC vs authority)"""
        giftmode = voice_engine.get_voice_profile("GiftMode")
        tinlance = voice_engine.get_voice_profile("Tinlance")
        assert giftmode["speed"] > tinlance["speed"]

    def test_webtemify_is_fastest(self, voice_engine):
        """WebTemify dev energy should be the fastest voice"""
        webtemify = voice_engine.get_voice_profile("WebTemify")
        giftmode = voice_engine.get_voice_profile("GiftMode")
        tinlance = voice_engine.get_voice_profile("Tinlance")
        assert webtemify["speed"] >= giftmode["speed"]
        assert webtemify["speed"] >= tinlance["speed"]

    def test_sample_rates_are_valid(self, voice_engine):
        """Sample rates must be standard audio values"""
        valid_rates = {16000, 22050, 24000, 44100, 48000}
        for brand in ["GiftMode", "Tinlance", "WebTemify"]:
            profile = voice_engine.get_voice_profile(brand)
            assert profile["sample_rate"] in valid_rates

    def test_speed_range_is_realistic(self, voice_engine):
        """Voice speed must be between 0.7x and 1.5x"""
        for brand in ["GiftMode", "Tinlance", "WebTemify"]:
            profile = voice_engine.get_voice_profile(brand)
            assert 0.7 <= profile["speed"] <= 1.5, \
                f"{brand} speed {profile['speed']} out of realistic range"

    def test_unknown_brand_raises_value_error(self, voice_engine):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            voice_engine.get_voice_profile("FakeBrand")


# ─────────────────────────────────────────────
# SYNTHESIS OUTPUT TESTS
# ─────────────────────────────────────────────

class TestVoiceSynthesis:

    def test_synthesize_returns_path(self, voice_engine, sample_script, output_path):
        """synthesize() must return the output WAV path"""
        with patch.object(voice_engine, '_run_tts') as mock_tts:
            mock_tts.side_effect = lambda text, path, profile: _make_wav(path)
            result = voice_engine.synthesize(
                text=sample_script,
                brand="GiftMode",
                output_path=str(output_path)
            )
        assert result == str(output_path)

    def test_output_file_exists_after_synthesis(self, voice_engine, sample_script, output_path):
        """Output WAV file must exist after synthesis"""
        with patch.object(voice_engine, '_run_tts') as mock_tts:
            mock_tts.side_effect = lambda text, path, profile: _make_wav(Path(path))
            voice_engine.synthesize(
                text=sample_script,
                brand="GiftMode",
                output_path=str(output_path)
            )
        assert output_path.exists()

    def test_output_is_valid_wav(self, voice_engine, sample_script, output_path):
        """Output must be a valid WAV file"""
        with patch.object(voice_engine, '_run_tts') as mock_tts:
            mock_tts.side_effect = lambda text, path, profile: _make_wav(Path(path))
            voice_engine.synthesize(
                text=sample_script,
                brand="GiftMode",
                output_path=str(output_path)
            )
        with wave.open(str(output_path), 'r') as wav:
            assert wav.getnchannels() == 1      # Mono
            assert wav.getsampwidth() == 2       # 16-bit
            assert wav.getnframes() > 0          # Has audio data

    def test_synthesize_calls_run_tts_once(self, voice_engine, sample_script, output_path):
        """_run_tts must be called exactly once per synthesize call"""
        with patch.object(voice_engine, '_run_tts') as mock_tts:
            mock_tts.side_effect = lambda text, path, profile: _make_wav(Path(path))
            voice_engine.synthesize(
                text=sample_script,
                brand="GiftMode",
                output_path=str(output_path)
            )
        assert mock_tts.call_count == 1

    def test_synthesize_passes_correct_brand_profile(self, voice_engine, sample_script, output_path):
        """_run_tts must receive the correct brand voice profile"""
        captured_profile = {}

        def capture(text, path, profile):
            captured_profile.update(profile)
            _make_wav(Path(path))

        with patch.object(voice_engine, '_run_tts', side_effect=capture):
            voice_engine.synthesize(
                text=sample_script,
                brand="GiftMode",
                output_path=str(output_path)
            )

        assert "speed" in captured_profile
        assert captured_profile["speed"] == voice_engine.get_voice_profile("GiftMode")["speed"]

    def test_empty_text_raises_value_error(self, voice_engine, output_path):
        """Empty text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            voice_engine.synthesize(text="", brand="GiftMode", output_path=str(output_path))

    def test_whitespace_text_raises_value_error(self, voice_engine, output_path):
        """Whitespace-only text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            voice_engine.synthesize(text="   ", brand="GiftMode", output_path=str(output_path))

    def test_unknown_brand_raises_value_error(self, voice_engine, sample_script, output_path):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            voice_engine.synthesize(
                text=sample_script,
                brand="UnknownBrand",
                output_path=str(output_path)
            )


# ─────────────────────────────────────────────
# DURATION ESTIMATION TESTS
# ─────────────────────────────────────────────

class TestDurationEstimation:

    def test_estimate_duration_returns_float(self, voice_engine, sample_script):
        """estimate_duration must return a float"""
        result = voice_engine.estimate_duration(sample_script, brand="GiftMode")
        assert isinstance(result, float)

    def test_estimate_duration_is_positive(self, voice_engine, sample_script):
        """Duration estimate must be positive"""
        result = voice_engine.estimate_duration(sample_script, brand="GiftMode")
        assert result > 0

    def test_faster_brand_has_shorter_duration(self, voice_engine, sample_script):
        """WebTemify (faster voice) should estimate shorter duration than Tinlance"""
        webtemify_dur = voice_engine.estimate_duration(sample_script, brand="WebTemify")
        tinlance_dur = voice_engine.estimate_duration(sample_script, brand="Tinlance")
        assert webtemify_dur < tinlance_dur

    def test_longer_text_gives_longer_duration(self, voice_engine):
        """Longer text must estimate longer duration"""
        short = "Buy this now."
        long = "I forgot her birthday three times. Each time worse than the last. This app fixed it."
        short_dur = voice_engine.estimate_duration(short, brand="GiftMode")
        long_dur = voice_engine.estimate_duration(long, brand="GiftMode")
        assert long_dur > short_dur

    def test_duration_in_realistic_range(self, voice_engine, sample_script):
        """Duration estimate for a typical script should be 15–40 seconds"""
        result = voice_engine.estimate_duration(sample_script, brand="GiftMode")
        assert 10 <= result <= 40, f"Duration {result}s out of realistic range"


# ─────────────────────────────────────────────
# WAV VALIDATION TESTS
# ─────────────────────────────────────────────

class TestWavValidation:

    def test_validate_wav_passes_for_valid_file(self, voice_engine, tmp_path):
        """validate_wav must return True for a valid WAV"""
        wav_path = _make_wav(tmp_path / "valid.wav")
        assert voice_engine.validate_wav(str(wav_path)) is True

    def test_validate_wav_fails_for_missing_file(self, voice_engine, tmp_path):
        """validate_wav must return False for non-existent file"""
        assert voice_engine.validate_wav(str(tmp_path / "missing.wav")) is False

    def test_validate_wav_fails_for_empty_file(self, voice_engine, tmp_path):
        """validate_wav must return False for empty file"""
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")
        assert voice_engine.validate_wav(str(empty)) is False

    def test_validate_wav_fails_for_zero_duration(self, voice_engine, tmp_path):
        """validate_wav must return False for WAV with no audio frames"""
        silent_path = tmp_path / "silent.wav"
        with wave.open(str(silent_path), 'w') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(22050)
            f.writeframes(b"")  # zero frames
        assert voice_engine.validate_wav(str(silent_path)) is False

    def test_validate_wav_fails_for_non_wav(self, voice_engine, tmp_path):
        """validate_wav must return False for non-WAV binary"""
        fake = tmp_path / "fake.wav"
        fake.write_bytes(b"not a wav file at all")
        assert voice_engine.validate_wav(str(fake)) is False
