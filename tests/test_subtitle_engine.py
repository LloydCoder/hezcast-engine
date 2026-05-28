"""
HezCast Engine — Subtitle Engine Tests
TDD Phase 3 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

faster-whisper transcription → word-level timestamps → ASS subtitle file
TikTok-style: bold, centered, word-highlighted captions
"""

import pytest
import os
import wave
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def subtitle_engine():
    from core.subtitle_engine import SubtitleEngine
    return SubtitleEngine()

@pytest.fixture
def sample_wav(tmp_path):
    """Valid 5-second WAV file"""
    path = tmp_path / "voice.wav"
    sample_rate = 22050
    num_frames = sample_rate * 5
    with wave.open(str(path), 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(struct.pack('<' + 'h' * num_frames, *([100] * num_frames)))
    return path

@pytest.fixture
def mock_transcription_segments():
    """Simulated faster-whisper output segments with word timestamps"""
    return [
        {
            "start": 0.0,
            "end": 2.5,
            "text": "Nobody told me you could forget twice",
            "words": [
                {"word": "Nobody",  "start": 0.0,  "end": 0.4},
                {"word": "told",    "start": 0.4,  "end": 0.65},
                {"word": "me",      "start": 0.65, "end": 0.8},
                {"word": "you",     "start": 0.8,  "end": 1.0},
                {"word": "could",   "start": 1.0,  "end": 1.3},
                {"word": "forget",  "start": 1.3,  "end": 1.7},
                {"word": "twice",   "start": 1.7,  "end": 2.5},
            ]
        },
        {
            "start": 2.5,
            "end": 5.0,
            "text": "GiftMode fixed it in seconds",
            "words": [
                {"word": "GiftMode", "start": 2.5,  "end": 3.0},
                {"word": "fixed",    "start": 3.0,  "end": 3.4},
                {"word": "it",       "start": 3.4,  "end": 3.6},
                {"word": "in",       "start": 3.6,  "end": 3.8},
                {"word": "seconds",  "start": 3.8,  "end": 5.0},
            ]
        }
    ]


# ─────────────────────────────────────────────
# TRANSCRIPTION TESTS
# ─────────────────────────────────────────────

class TestTranscription:

    def test_transcribe_returns_segments(self, subtitle_engine, sample_wav, mock_transcription_segments):
        """transcribe() must return a list of segments"""
        with patch.object(subtitle_engine, '_run_whisper', return_value=mock_transcription_segments):
            result = subtitle_engine.transcribe(str(sample_wav))
        assert isinstance(result, list)
        assert len(result) > 0

    def test_each_segment_has_required_keys(self, subtitle_engine, sample_wav, mock_transcription_segments):
        """Each segment must have start, end, text, words"""
        with patch.object(subtitle_engine, '_run_whisper', return_value=mock_transcription_segments):
            segments = subtitle_engine.transcribe(str(sample_wav))
        for seg in segments:
            assert "start" in seg
            assert "end" in seg
            assert "text" in seg
            assert "words" in seg

    def test_each_word_has_timestamps(self, subtitle_engine, sample_wav, mock_transcription_segments):
        """Every word entry must have start, end, and word keys"""
        with patch.object(subtitle_engine, '_run_whisper', return_value=mock_transcription_segments):
            segments = subtitle_engine.transcribe(str(sample_wav))
        for seg in segments:
            for word in seg["words"]:
                assert "word" in word
                assert "start" in word
                assert "end" in word

    def test_segment_timestamps_are_sequential(self, subtitle_engine, sample_wav, mock_transcription_segments):
        """Segment start times must be non-decreasing"""
        with patch.object(subtitle_engine, '_run_whisper', return_value=mock_transcription_segments):
            segments = subtitle_engine.transcribe(str(sample_wav))
        starts = [s["start"] for s in segments]
        assert starts == sorted(starts)

    def test_word_end_after_start(self, subtitle_engine, sample_wav, mock_transcription_segments):
        """Every word's end time must be after its start time"""
        with patch.object(subtitle_engine, '_run_whisper', return_value=mock_transcription_segments):
            segments = subtitle_engine.transcribe(str(sample_wav))
        for seg in segments:
            for w in seg["words"]:
                assert w["end"] >= w["start"], \
                    f"Word '{w['word']}' has end ({w['end']}) < start ({w['start']})"

    def test_transcribe_nonexistent_file_raises(self, subtitle_engine):
        """Non-existent audio file must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            subtitle_engine.transcribe("/nonexistent/audio.wav")

    def test_transcribe_empty_path_raises(self, subtitle_engine):
        """Empty path must raise ValueError"""
        with pytest.raises(ValueError, match="audio_path"):
            subtitle_engine.transcribe("")


# ─────────────────────────────────────────────
# ASS SUBTITLE GENERATION TESTS
# ─────────────────────────────────────────────

class TestASSGeneration:

    def test_generate_ass_returns_string(self, subtitle_engine, mock_transcription_segments):
        """generate_ass() must return a string"""
        result = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        assert isinstance(result, str)

    def test_ass_has_script_info_section(self, subtitle_engine, mock_transcription_segments):
        """ASS file must have [Script Info] section"""
        ass = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        assert "[Script Info]" in ass

    def test_ass_has_v4_styles_section(self, subtitle_engine, mock_transcription_segments):
        """ASS file must have [V4+ Styles] section"""
        ass = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        assert "[V4+ Styles]" in ass

    def test_ass_has_events_section(self, subtitle_engine, mock_transcription_segments):
        """ASS file must have [Events] section"""
        ass = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        assert "[Events]" in ass

    def test_ass_has_dialogue_lines(self, subtitle_engine, mock_transcription_segments):
        """ASS must contain Dialogue lines for each segment"""
        ass = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        dialogue_count = ass.count("Dialogue:")
        assert dialogue_count >= len(mock_transcription_segments)

    def test_ass_contains_script_text(self, subtitle_engine, mock_transcription_segments):
        """ASS must contain actual transcript words"""
        ass = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        assert "Nobody" in ass or "nobody" in ass.lower()
        assert "GiftMode" in ass or "giftmode" in ass.lower()

    def test_ass_uses_brand_subtitle_color(self, subtitle_engine, mock_transcription_segments):
        """ASS styles must include the brand's subtitle color"""
        ass_giftmode = subtitle_engine.generate_ass(
            segments=mock_transcription_segments,
            brand="GiftMode"
        )
        # GiftMode subtitle color is #FF6B9D — in ASS format: &H009D6BFF
        assert "FF6B9D" in ass_giftmode.upper() or "9D6BFF" in ass_giftmode.upper()

    def test_different_brands_produce_different_styles(self, subtitle_engine, mock_transcription_segments):
        """Different brands must produce ASS with different color codes"""
        ass_giftmode = subtitle_engine.generate_ass(
            segments=mock_transcription_segments, brand="GiftMode"
        )
        ass_tinlance = subtitle_engine.generate_ass(
            segments=mock_transcription_segments, brand="Tinlance"
        )
        # Extract style lines only for comparison
        giftmode_styles = [l for l in ass_giftmode.split('\n') if 'Style:' in l]
        tinlance_styles = [l for l in ass_tinlance.split('\n') if 'Style:' in l]
        assert giftmode_styles != tinlance_styles

    def test_unknown_brand_raises(self, subtitle_engine, mock_transcription_segments):
        """Unknown brand must raise ValueError"""
        with pytest.raises(ValueError, match="Unknown brand"):
            subtitle_engine.generate_ass(
                segments=mock_transcription_segments,
                brand="FakeBrand"
            )

    def test_empty_segments_raises(self, subtitle_engine):
        """Empty segments list must raise ValueError"""
        with pytest.raises(ValueError, match="segments"):
            subtitle_engine.generate_ass(segments=[], brand="GiftMode")


# ─────────────────────────────────────────────
# FILE SAVE TESTS
# ─────────────────────────────────────────────

class TestSubtitleFileSave:

    def test_save_ass_creates_file(self, subtitle_engine, mock_transcription_segments, tmp_path):
        """save_ass() must create the .ass file on disk"""
        output_path = tmp_path / "subtitles.ass"
        subtitle_engine.save_ass(
            segments=mock_transcription_segments,
            brand="GiftMode",
            output_path=str(output_path)
        )
        assert output_path.exists()

    def test_saved_ass_is_not_empty(self, subtitle_engine, mock_transcription_segments, tmp_path):
        """Saved .ass file must not be empty"""
        output_path = tmp_path / "subtitles.ass"
        subtitle_engine.save_ass(
            segments=mock_transcription_segments,
            brand="GiftMode",
            output_path=str(output_path)
        )
        assert output_path.stat().st_size > 0

    def test_saved_ass_is_valid_utf8(self, subtitle_engine, mock_transcription_segments, tmp_path):
        """Saved .ass file must be valid UTF-8"""
        output_path = tmp_path / "subtitles.ass"
        subtitle_engine.save_ass(
            segments=mock_transcription_segments,
            brand="GiftMode",
            output_path=str(output_path)
        )
        content = output_path.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_save_ass_returns_path(self, subtitle_engine, mock_transcription_segments, tmp_path):
        """save_ass() must return the output path string"""
        output_path = tmp_path / "subtitles.ass"
        result = subtitle_engine.save_ass(
            segments=mock_transcription_segments,
            brand="GiftMode",
            output_path=str(output_path)
        )
        assert result == str(output_path)

    def test_save_ass_creates_parent_dirs(self, subtitle_engine, mock_transcription_segments, tmp_path):
        """save_ass() must create parent directories if needed"""
        deep_path = tmp_path / "deep" / "nested" / "subs.ass"
        subtitle_engine.save_ass(
            segments=mock_transcription_segments,
            brand="GiftMode",
            output_path=str(deep_path)
        )
        assert deep_path.exists()


# ─────────────────────────────────────────────
# COVERAGE CALCULATION TESTS
# ─────────────────────────────────────────────

class TestSubtitleCoverage:

    def test_coverage_returns_float(self, subtitle_engine, mock_transcription_segments):
        """calculate_coverage() must return a float"""
        result = subtitle_engine.calculate_coverage(
            segments=mock_transcription_segments,
            total_duration=5.0
        )
        assert isinstance(result, float)

    def test_coverage_is_between_0_and_1(self, subtitle_engine, mock_transcription_segments):
        """Coverage must be in [0.0, 1.0]"""
        result = subtitle_engine.calculate_coverage(
            segments=mock_transcription_segments,
            total_duration=5.0
        )
        assert 0.0 <= result <= 1.0

    def test_full_coverage_is_near_1(self, subtitle_engine, mock_transcription_segments):
        """Segments covering the full duration should give coverage ~1.0"""
        result = subtitle_engine.calculate_coverage(
            segments=mock_transcription_segments,
            total_duration=5.0
        )
        assert result >= 0.85  # Allow small gaps between words

    def test_zero_duration_raises(self, subtitle_engine, mock_transcription_segments):
        """total_duration=0 must raise ValueError"""
        with pytest.raises(ValueError, match="duration"):
            subtitle_engine.calculate_coverage(
                segments=mock_transcription_segments,
                total_duration=0.0
            )

    def test_empty_segments_gives_zero_coverage(self, subtitle_engine):
        """Empty segments must give 0.0 coverage"""
        result = subtitle_engine.calculate_coverage(
            segments=[],
            total_duration=25.0
        )
        assert result == 0.0
