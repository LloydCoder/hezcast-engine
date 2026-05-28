"""
HezCast Engine — Subtitle Engine
Tinlance Limited | Apache 2.0

Transcribes voice audio using faster-whisper and generates
TikTok-style ASS subtitle files with per-brand colors.

ASS format chosen over SRT because it supports:
  - Word-level timing (karaoke-style highlighting)
  - Custom fonts, sizes, positions
  - Drop shadows and outlines
  - Centered, bold, large text (TikTok aesthetic)

In Docker: uses real faster-whisper with large-v3 model
In tests:  _run_whisper is mocked
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# BRAND SUBTITLE STYLES
# ─────────────────────────────────────────────

# ASS color format: &HAABBGGRR (alpha, blue, green, red — reversed hex)
def _hex_to_ass(hex_color: str) -> str:
    """Convert #RRGGBB to ASS &H00BBGGRR format"""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}"

BRAND_SUBTITLE_STYLES = {
    "GiftMode": {
        "primary_hex":    "#FF6B9D",
        "font_name":      "Arial",
        "font_size":      52,
        "bold":           1,
        "outline":        3,
        "shadow":         2,
        "margin_v":       120,  # From bottom
        "alignment":      2,    # Centered bottom (ASS alignment)
        "background_alpha": "80",
    },
    "Tinlance": {
        "primary_hex":    "#00D4FF",
        "font_name":      "Arial",
        "font_size":      48,
        "bold":           1,
        "outline":        3,
        "shadow":         2,
        "margin_v":       120,
        "alignment":      2,
        "background_alpha": "80",
    },
    "WebTemify": {
        "primary_hex":    "#7C3AED",
        "font_name":      "Arial",
        "font_size":      50,
        "bold":           1,
        "outline":        3,
        "shadow":         2,
        "margin_v":       120,
        "alignment":      2,
        "background_alpha": "80",
    },
}


class SubtitleEngine:
    """
    Generates TikTok-style ASS subtitle files from voice audio.

    Pipeline:
        WAV → faster-whisper → word timestamps → ASS file

    Usage:
        engine = SubtitleEngine()
        segments = engine.transcribe("/storage/inputs/job_id/voice.wav")
        ass_path = engine.save_ass(segments, brand="GiftMode", output_path="subs.ass")
        coverage = engine.calculate_coverage(segments, total_duration=25.0)
    """

    # Whisper model size (tradeoff: accuracy vs speed)
    WHISPER_MODEL = "base"     # "base" for dev, "large-v3" for prod
    WHISPER_DEVICE = "cpu"     # "cuda" when GPU available
    WHISPER_COMPUTE = "int8"   # Fastest on CPU

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"
        with open(config_path) as f:
            self.brand_config = json.load(f)
        self._whisper_model = None

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def transcribe(self, audio_path: str) -> list[dict]:
        """
        Transcribe audio to word-level timestamped segments.

        Args:
            audio_path: Path to WAV or MP3 file

        Returns:
            List of segment dicts, each with:
            {start, end, text, words: [{word, start, end}]}

        Raises:
            ValueError:        If audio_path is empty
            FileNotFoundError: If audio file doesn't exist
        """
        if not audio_path or not audio_path.strip():
            raise ValueError("audio_path must be a non-empty string")

        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Transcribing audio: {audio_path}")
        segments = self._run_whisper(audio_path)

        # Ensure sequential timestamps
        segments = sorted(segments, key=lambda s: s["start"])

        logger.info(f"Transcription complete | segments={len(segments)}")
        return segments

    def generate_ass(self, segments: list[dict], brand: str) -> str:
        """
        Generate ASS subtitle content from transcript segments.

        Args:
            segments: List of segment dicts from transcribe()
            brand:    Brand name for style config

        Returns:
            ASS file content as string

        Raises:
            ValueError: If segments empty or brand unknown
        """
        if not segments:
            raise ValueError("segments must be a non-empty list")

        if brand not in BRAND_SUBTITLE_STYLES:
            available = list(BRAND_SUBTITLE_STYLES.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available: {available}"
            )

        style = BRAND_SUBTITLE_STYLES[brand]
        primary_ass = _hex_to_ass(style["primary_hex"])
        white_ass   = "&H00FFFFFF"
        black_ass   = "&H00000000"

        lines = []

        # ── [Script Info] ───────────────────────
        lines += [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "ScaledBorderAndShadow: yes",
            "",
        ]

        # ── [V4+ Styles] ────────────────────────
        lines += [
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            # Main subtitle style
            f"Style: Default,{style['font_name']},{style['font_size']},"
            f"{white_ass},{primary_ass},{black_ass},&H{style['background_alpha']}000000,"
            f"{style['bold']},0,0,0,"
            f"100,100,0,0,1,{style['outline']},{style['shadow']},"
            f"{style['alignment']},60,60,{style['margin_v']},1",
            # Highlighted word style (active word in karaoke)
            f"Style: Highlight,{style['font_name']},{style['font_size']},"
            f"{primary_ass},{primary_ass},{black_ass},&H{style['background_alpha']}000000,"
            f"{style['bold']},0,0,0,"
            f"100,100,0,0,1,{style['outline']},{style['shadow']},"
            f"{style['alignment']},60,60,{style['margin_v']},1",
            "",
        ]

        # ── [Events] ────────────────────────────
        lines += [
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        # Generate one Dialogue line per segment
        for seg in segments:
            start_ts = self._seconds_to_ass_time(seg["start"])
            end_ts   = self._seconds_to_ass_time(seg["end"])
            text     = seg["text"].strip()

            # Build karaoke-style text with word-level timing
            if seg.get("words"):
                text = self._build_karaoke_text(seg["words"], seg["start"])
            else:
                # Fallback: no word timing, use plain text
                text = text.upper() if len(text.split()) <= 4 else text

            lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}"
            )

        return "\n".join(lines)

    def save_ass(
        self,
        segments: list[dict],
        brand: str,
        output_path: str
    ) -> str:
        """
        Generate and save ASS subtitle file to disk.

        Args:
            segments:    Transcript segments from transcribe()
            brand:       Brand name for styling
            output_path: Destination path for .ass file

        Returns:
            output_path (str)
        """
        content = self.generate_ass(segments, brand)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        logger.info(f"Subtitles saved: {output_path}")
        return output_path

    def calculate_coverage(
        self,
        segments: list[dict],
        total_duration: float
    ) -> float:
        """
        Calculate what fraction of the total duration has subtitle coverage.

        Args:
            segments:       Transcript segments
            total_duration: Total video duration in seconds

        Returns:
            float in [0.0, 1.0]

        Raises:
            ValueError: If total_duration <= 0
        """
        if total_duration <= 0:
            raise ValueError(
                f"total_duration must be > 0 (got {total_duration})"
            )

        if not segments:
            return 0.0

        covered = sum(
            max(0.0, seg["end"] - seg["start"])
            for seg in segments
        )
        return min(1.0, round(covered / total_duration, 4))

    # ─────────────────────────────────────────
    # WHISPER (mockable in tests)
    # ─────────────────────────────────────────

    def _run_whisper(self, audio_path: str) -> list[dict]:
        """
        Run faster-whisper transcription.
        In tests: this method is mocked.

        Returns list of segment dicts with word-level timestamps.
        """
        if self._whisper_model is None:
            self._load_whisper()

        result_segments = []
        segments, _ = self._whisper_model.transcribe(
            audio_path,
            word_timestamps=True,
            language="en",
            beam_size=5,
            vad_filter=True,   # Skip silent regions
        )

        for seg in segments:
            words = []
            if hasattr(seg, 'words') and seg.words:
                words = [
                    {
                        "word":  w.word.strip(),
                        "start": round(w.start, 3),
                        "end":   round(w.end, 3),
                    }
                    for w in seg.words
                ]

            result_segments.append({
                "start": round(seg.start, 3),
                "end":   round(seg.end, 3),
                "text":  seg.text.strip(),
                "words": words,
            })

        return result_segments

    def _load_whisper(self) -> None:
        """Lazy-load faster-whisper model"""
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading Whisper model: {self.WHISPER_MODEL}")
            self._whisper_model = WhisperModel(
                self.WHISPER_MODEL,
                device=self.WHISPER_DEVICE,
                compute_type=self.WHISPER_COMPUTE,
            )
            logger.info("Whisper model loaded")
        except ImportError:
            raise SubtitleError(
                "faster-whisper not installed. "
                "Run: pip install faster-whisper"
            )

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────

    def _seconds_to_ass_time(self, seconds: float) -> str:
        """Convert seconds to ASS timestamp format H:MM:SS.cc"""
        h  = int(seconds // 3600)
        m  = int((seconds % 3600) // 60)
        s  = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _build_karaoke_text(
        self,
        words: list[dict],
        segment_start: float
    ) -> str:
        """
        Build ASS karaoke-style text with word-level timing.

        Each word gets a {\k<cs>} tag where cs = centiseconds duration.
        Active word appears highlighted; past words are white.

        Example output:
            {k40}Nobody {k25}told {k15}me {k20}you {k30}could {k40}forget {k80}twice
        """
        parts = []
        for word in words:
            duration_cs = max(1, int((word["end"] - word["start"]) * 100))
            text = word["word"].strip()
            parts.append(f"{{\\k{duration_cs}}}{text}")
        return " ".join(parts)


# ─────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────

class SubtitleError(Exception):
    """Raised when subtitle generation fails"""
    pass
