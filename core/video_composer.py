"""
HezCast Engine — Video Composer
Tinlance Limited | Apache 2.0

FFmpeg orchestration layer. Assembles final MP4 from:
  - Background clip (semantic stock video, looped to duration)
  - Voice audio (Piper TTS WAV)
  - Avatar overlay (MuseTalk talking head — commercial layer)
  - Brand lower-third (logo + CTA banner)
  - Subtitle overlay (ASS caption file)

Output: 1080x1920 H.264/AAC MP4, ready for TikTok/Reels/Shorts
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# BRAND OVERLAY CONFIGS
# ─────────────────────────────────────────────
BRAND_OVERLAYS = {
    "GiftMode": {
        "primary_color":   "#FF6B9D",
        "secondary_color": "#FFE4F0",
        "subtitle_color":  "#FF6B9D",
        "cta_text":        "Download GiftMode free →",
        "font":            "Arial-Bold",
    },
    "Tinlance": {
        "primary_color":   "#00D4FF",
        "secondary_color": "#0A0E1A",
        "subtitle_color":  "#00D4FF",
        "cta_text":        "Book a consultation → tinlance.com",
        "font":            "Arial-Bold",
    },
    "WebTemify": {
        "primary_color":   "#7C3AED",
        "secondary_color": "#F5F3FF",
        "subtitle_color":  "#7C3AED",
        "cta_text":        "Get the template → webtemify.com",
        "font":            "Arial-Bold",
    },
}

# Output spec
OUTPUT_WIDTH  = 1080
OUTPUT_HEIGHT = 1920
VIDEO_CODEC   = "libx264"
AUDIO_CODEC   = "aac"
CRF           = 23          # Quality: lower = better (18=high, 28=low)
PRESET        = "fast"      # Encoding speed vs compression


class VideoComposer:
    """
    Assembles final 9:16 MP4 from pipeline components using FFmpeg.

    Usage:
        composer = VideoComposer()
        output = composer.compose({
            "job_id":        "abc123",
            "brand":         "GiftMode",
            "voice_path":    "/storage/inputs/abc123/voice.wav",
            "bg_clip_path":  "/storage/clips/pexels_1234.mp4",
            "subtitle_path": "/storage/inputs/abc123/subtitles.ass",
            "output_path":   "/storage/outputs/abc123/final.mp4",
            "duration_sec":  25.0,
        })
    """

    REQUIRED_FIELDS = ["job_id", "brand", "voice_path", "output_path"]

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"
        with open(config_path) as f:
            self.brand_config = json.load(f)
        self.ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def compose(self, request: dict) -> str:
        """
        Compose final MP4 from pipeline components.

        Args:
            request: dict with keys:
                job_id        (str, required)
                brand         (str, required)
                voice_path    (str, required)  WAV audio
                output_path   (str, required)  destination MP4
                bg_clip_path  (str, optional)  background video
                subtitle_path (str, optional)  .ass subtitle file
                avatar_path   (str, optional)  talking head MP4
                duration_sec  (float, optional) target duration

        Returns:
            output_path (str)

        Raises:
            ValueError:          Invalid or missing fields
            FileNotFoundError:   Required input file missing
            VideoComposeError:   FFmpeg execution failed
        """
        self._validate_compose_request(request)

        output_path = request["output_path"]
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = self._build_ffmpeg_cmd(request)

        logger.info(
            f"Composing video | job={request['job_id']} | "
            f"brand={request['brand']} | output={output_path}"
        )

        self._run_ffmpeg(cmd, output_path)

        logger.info(f"Compose complete | output={output_path}")
        return output_path

    def get_brand_overlay(self, brand: str) -> dict:
        """
        Get brand overlay config (colors, CTA, font).

        Raises:
            ValueError: If brand is unknown
        """
        if brand not in BRAND_OVERLAYS:
            available = list(BRAND_OVERLAYS.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available: {available}"
            )
        return BRAND_OVERLAYS[brand].copy()

    # ─────────────────────────────────────────
    # FFMPEG COMMAND BUILDER
    # ─────────────────────────────────────────

    def _build_ffmpeg_cmd(self, request: dict) -> list:
        """
        Build the complete FFmpeg command for this job.

        Layer order (bottom to top):
          1. Background (stock clip or solid color)
          2. Avatar overlay (if provided)
          3. Subtitle ASS overlay
          4. Brand lower-third CTA

        Returns:
            list of command tokens (suitable for subprocess)
        """
        brand    = request["brand"]
        voice    = request["voice_path"]
        output   = request["output_path"]
        duration = request.get("duration_sec", 30.0)
        bg_clip  = request.get("bg_clip_path")
        subtitle = request.get("subtitle_path")
        avatar   = request.get("avatar_path")
        overlay  = self.get_brand_overlay(brand)

        cmd = ["ffmpeg", "-y"]

        # ── INPUTS ──────────────────────────────

        # Input 0: background video or generated color source
        if bg_clip and Path(bg_clip).exists():
            cmd += ["-stream_loop", "-1", "-i", bg_clip]
        else:
            # Solid color background using FFmpeg lavfi
            cmd += [
                "-f", "lavfi",
                "-i", f"color=c=0x080A0F:size={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:rate=30"
            ]

        # Input 1: voice audio
        cmd += ["-i", voice]

        # Input 2 (optional): avatar overlay video
        if avatar and Path(avatar).exists():
            cmd += ["-i", avatar]

        # ── FILTER COMPLEX ──────────────────────
        filters = []
        n_inputs = 2 + (1 if avatar and Path(avatar or "").exists() else 0)

        # Scale background to 1080x1920, crop to fill
        filters.append(
            f"[0:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
            f"setpts=PTS-STARTPTS[bg]"
        )

        current_v = "[bg]"

        # Overlay avatar if present
        if avatar and Path(avatar or "").exists():
            # Scale avatar to 60% width, center-bottom
            avatar_w = int(OUTPUT_WIDTH * 0.6)
            avatar_x = int((OUTPUT_WIDTH - avatar_w) / 2)
            avatar_y = int(OUTPUT_HEIGHT * 0.15)
            filters.append(
                f"[2:v]scale={avatar_w}:-1[av]"
            )
            filters.append(
                f"{current_v}[av]overlay={avatar_x}:{avatar_y}[with_avatar]"
            )
            current_v = "[with_avatar]"

        # Add subtitle overlay
        if subtitle and Path(subtitle).exists():
            # Escape path for FFmpeg filter
            esc_sub = str(subtitle).replace("\\", "/").replace(":", "\\:")
            filters.append(
                f"{current_v}ass='{esc_sub}'[with_subs]"
            )
            current_v = "[with_subs]"

        # Add brand CTA lower-third text
        cta_text = overlay["cta_text"].replace("'", "\\'").replace("→", "->")
        hex_color = overlay["primary_color"].lstrip("#")
        # Convert hex color to FFmpeg format (0xRRGGBB)
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        ffmpeg_color = f"0x{r}{g}{b}"

        filters.append(
            f"{current_v}drawtext="
            f"text='{cta_text}':"
            f"fontsize=28:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y=h-80:"
            f"box=1:"
            f"boxcolor={ffmpeg_color}@0.85:"
            f"boxborderw=12:"
            f"font=Arial-Bold"
            f"[vout]"
        )

        cmd += ["-filter_complex", ";".join(filters)]
        cmd += ["-map", "[vout]", "-map", "1:a"]

        # ── OUTPUT SETTINGS ─────────────────────
        cmd += [
            "-t",        str(duration),
            "-c:v",      VIDEO_CODEC,
            "-crf",      str(CRF),
            "-preset",   PRESET,
            "-c:a",      AUDIO_CODEC,
            "-b:a",      "128k",
            "-ar",       "44100",
            "-pix_fmt",  "yuv420p",   # Maximum compatibility
            "-movflags", "+faststart", # Web streaming optimization
            output
        ]

        return cmd

    # ─────────────────────────────────────────
    # FFMPEG RUNNER (mockable in tests)
    # ─────────────────────────────────────────

    def _run_ffmpeg(self, cmd: list, output_path: str) -> None:
        """
        Execute FFmpeg subprocess.
        In tests: this method is mocked.

        Raises:
            VideoComposeError: If FFmpeg returns non-zero exit code
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300   # 5 minute timeout
            )
            if result.returncode != 0:
                raise VideoComposeError(
                    f"FFmpeg failed (code {result.returncode}):\n"
                    f"{result.stderr[-500:]}"
                )
        except subprocess.TimeoutExpired:
            raise VideoComposeError("FFmpeg timed out after 300s")
        except FileNotFoundError:
            raise VideoComposeError(
                "FFmpeg binary not found. "
                "Install FFmpeg: apt-get install ffmpeg"
            )

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    def _validate_compose_request(self, request: dict) -> None:
        """Validate all required fields and file existence"""
        for field in self.REQUIRED_FIELDS:
            if field not in request:
                raise ValueError(f"Missing required field: {field}")

        brand = request["brand"]
        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )

        if not request.get("output_path"):
            raise ValueError("output_path must be a non-empty string")

        voice_path = request.get("voice_path")
        if voice_path and not Path(voice_path).exists():
            raise FileNotFoundError(
                f"voice file not found: {voice_path}"
            )

        duration = request.get("duration_sec", 1.0)
        if float(duration) <= 0:
            raise ValueError(
                f"duration_sec must be > 0 (got {duration})"
            )


# ─────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────

class VideoComposeError(Exception):
    """Raised when FFmpeg fails or times out"""
    pass
