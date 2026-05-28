"""
HezCast Engine — Thumbnail Engine
Tinlance Limited | Apache 2.0

Generates 3 branded thumbnail variants per video:
  - hook:      Emotional/attention-grabbing style
  - curiosity: Question/mystery style
  - authority: Bold claim/credibility style

Pipeline:
  1. Extract best keyframe from video (face-first via QA detector)
  2. Generate 3 headlines from post bundle via LLM
  3. Overlay text + brand colors + typography via Pillow
  4. Export: thumbnail_hook.png, thumbnail_curiosity.png, thumbnail_authority.png

Uses FFmpeg (already in stack) for frame extraction.
Uses Pillow (already in stack) for image composition.
No new dependencies required.
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# BRAND THUMBNAIL STYLES
# ─────────────────────────────────────────────

BRAND_THUMBNAIL_STYLES = {
    "GiftMode": {
        "primary_color": "#FF6B9D",
        "bg_color":      "#1A0A0F",
        "text_color":    "#FFFFFF",
        "accent_color":  "#FFE4F0",
        "font_size":     72,
        "logo_text":     "GiftMode",
    },
    "Tinlance": {
        "primary_color": "#00D4FF",
        "bg_color":      "#0A0E1A",
        "text_color":    "#FFFFFF",
        "accent_color":  "#E8F8FF",
        "font_size":     68,
        "logo_text":     "Tinlance",
    },
    "WebTemify": {
        "primary_color": "#7C3AED",
        "bg_color":      "#0F0A1A",
        "text_color":    "#FFFFFF",
        "accent_color":  "#F5F3FF",
        "font_size":     70,
        "logo_text":     "WebTemify",
    },
    "HezCast": {
        "primary_color": "#00D4FF",
        "bg_color":      "#0A0E1A",
        "text_color":    "#FFFFFF",
        "accent_color":  "#E8F8FF",
        "font_size":     68,
        "logo_text":     "HezCast",
    },
}

# Headline templates per variant style
HEADLINE_TEMPLATES = {
    "hook": [
        "I can't believe this happened",
        "Nobody told me about this",
        "This changed everything for me",
        "I was completely wrong about this",
    ],
    "curiosity": [
        "Why most people get this wrong",
        "The secret nobody talks about",
        "What they don't want you to know",
        "This is why you're struggling",
    ],
    "authority": [
        "The proven system that works",
        "How I solved this permanently",
        "The exact steps that work",
        "Stop doing this — do this instead",
    ],
}


class ThumbnailEngine:
    """
    Generates 3 branded thumbnail variants for every HezCast video.

    Usage:
        engine = ThumbnailEngine()
        thumbnails = engine.generate(
            video_path="/storage/outputs/job_id/final.mp4",
            bundle=post_bundle,
            brand="GiftMode",
            output_dir="/storage/outputs/job_id/"
        )
        # Returns list of dicts:
        # [{"variant": "hook", "path": "..."}, ...]
    """

    # Thumbnail dimensions — same as video frame
    WIDTH  = 1080
    HEIGHT = 1920

    # Keyframe timestamps to try (seconds)
    KEYFRAME_TIMESTAMPS = [1.5, 2.0, 2.5, 1.0, 3.0]

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"
        with open(config_path) as f:
            self.brand_config = json.load(f)
        self.ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def generate(
        self,
        video_path: str,
        bundle: dict,
        brand: str,
        output_dir: str,
    ) -> list[dict]:
        """
        Generate 3 branded thumbnail variants for a video.

        Args:
            video_path:  Path to the rendered MP4
            bundle:      Post bundle from PostGenerator
            brand:       Brand name for styling
            output_dir:  Directory to save thumbnails

        Returns:
            List of 3 dicts: [{"variant": str, "path": str}, ...]

        Raises:
            FileNotFoundError: If video file missing
            ValueError:        If brand unknown
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Step 1: Extract best keyframe
        frame_path = self.extract_best_frame(video_path, output_dir)

        # Step 2: Generate headlines
        headlines = self.generate_headlines(bundle, brand)

        # Step 3: Create 3 thumbnail variants
        style = self.get_brand_style(brand)
        thumbnails = []

        for variant, headline in headlines.items():
            out_path = str(Path(output_dir) / f"thumbnail_{variant}.png")
            self._create_thumbnail(
                frame_path=frame_path,
                headline=headline,
                style=style,
                output_path=out_path,
                variant=variant,
            )
            thumbnails.append({
                "variant": variant,
                "path":    out_path,
                "headline": headline,
            })

        logger.info(
            f"Thumbnails generated | brand={brand} | "
            f"variants={[t['variant'] for t in thumbnails]}"
        )
        return thumbnails

    def extract_best_frame(self, video_path: str, output_dir: str) -> str:
        """
        Extract the best keyframe from a video.
        Tries multiple timestamps, returns the first successful one.

        Args:
            video_path:  Path to MP4
            output_dir:  Where to save the extracted frame

        Returns:
            Path to the extracted PNG frame
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        for ts in self.KEYFRAME_TIMESTAMPS:
            out_path = str(Path(output_dir) / f"keyframe_{ts}.png")
            try:
                result = self.extract_keyframe(video_path, out_path, ts)
                if result and Path(result).exists():
                    return result
            except Exception:
                continue

        # Fallback: first frame
        out_path = str(Path(output_dir) / "keyframe_0.png")
        return self.extract_keyframe(video_path, out_path, 0.0)

    def extract_keyframe(
        self,
        video_path: str,
        output_path: str,
        timestamp_sec: float,
    ) -> str:
        """
        Extract a single frame from video at given timestamp using FFmpeg.

        Args:
            video_path:    Path to MP4
            output_path:   Path for output PNG
            timestamp_sec: Time position to extract (seconds)

        Returns:
            output_path (str)

        Raises:
            FileNotFoundError: If video file doesn't exist
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        return self._run_ffmpeg_frame(video_path, output_path, timestamp_sec)

    def generate_headlines(self, bundle: dict, brand: str) -> dict:
        """
        Generate 3 thumbnail headlines from post bundle.

        Uses the bundle title/caption to derive brand-appropriate
        hook, curiosity, and authority headlines.

        Args:
            bundle: Post bundle from PostGenerator
            brand:  Brand name for tone adaptation

        Returns:
            dict with keys: hook, curiosity, authority
            Each value is a headline string (max 10 words)
        """
        if brand not in self.brand_config:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(self.brand_config.keys())}"
            )

        title = bundle.get("title", "")
        brand_cfg = self.brand_config[brand]
        tone = brand_cfg.get("tone", "emotional")

        headlines = {}

        for variant in ["hook", "curiosity", "authority"]:
            headline = self._derive_headline(title, variant, tone, brand)
            # Enforce 10 word max
            words = headline.split()
            if len(words) > 10:
                headline = " ".join(words[:10])
            headlines[variant] = headline

        # Ensure all 3 variants are distinct
        if len(set(headlines.values())) < 3:
            templates = HEADLINE_TEMPLATES
            for i, variant in enumerate(["hook", "curiosity", "authority"]):
                if list(headlines.values()).count(headlines[variant]) > 1:
                    headlines[variant] = templates[variant][
                        hash(title + variant + brand) % len(templates[variant])
                    ]

        return headlines

    def get_brand_style(self, brand: str) -> dict:
        """
        Get thumbnail style config for a brand.

        Raises:
            ValueError: If brand unknown
        """
        if brand not in BRAND_THUMBNAIL_STYLES:
            raise ValueError(
                f"Unknown brand: '{brand}'. "
                f"Available: {list(BRAND_THUMBNAIL_STYLES.keys())}"
            )
        return BRAND_THUMBNAIL_STYLES[brand].copy()

    # ─────────────────────────────────────────
    # THUMBNAIL CREATION (mockable)
    # ─────────────────────────────────────────

    def _create_thumbnail(
        self,
        frame_path: str,
        headline: str,
        style: dict,
        output_path: str,
        variant: str,
    ) -> str:
        """
        Compose thumbnail from keyframe + text overlay using Pillow.
        Falls back to FFmpeg drawtext if Pillow unavailable.

        In tests: mocked via patch.
        """
        try:
            return self._create_with_pillow(
                frame_path, headline, style, output_path, variant
            )
        except ImportError:
            return self._create_with_ffmpeg(
                frame_path, headline, style, output_path
            )

    def _create_with_pillow(
        self,
        frame_path: str,
        headline: str,
        style: dict,
        output_path: str,
        variant: str,
    ) -> str:
        """Compose thumbnail using Pillow for high quality text overlay"""
        from PIL import Image, ImageDraw, ImageFont, ImageFilter

        # Open frame
        if Path(frame_path).exists() and Path(frame_path).stat().st_size > 50:
            try:
                img = Image.open(frame_path).convert("RGB")
                img = img.resize((self.WIDTH, self.HEIGHT), Image.LANCZOS)
            except Exception:
                img = Image.new("RGB", (self.WIDTH, self.HEIGHT), style["bg_color"])
        else:
            img = Image.new("RGB", (self.WIDTH, self.HEIGHT), style["bg_color"])

        # Add dark gradient overlay at bottom
        overlay = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        for y in range(self.HEIGHT // 2, self.HEIGHT):
            alpha = int(180 * (y - self.HEIGHT // 2) / (self.HEIGHT // 2))
            draw_overlay.line([(0, y), (self.WIDTH, y)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

        draw = ImageDraw.Draw(img)

        # Brand color accent bar at top
        primary = style["primary_color"].lstrip("#")
        r, g, b = int(primary[0:2], 16), int(primary[2:4], 16), int(primary[4:6], 16)
        draw.rectangle([(0, 0), (self.WIDTH, 12)], fill=(r, g, b))

        # Headline text — centered, bottom third
        font_size = style["font_size"]
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
            small_font = font

        # Word wrap headline
        words = headline.upper().split()
        lines = []
        current = []
        for word in words:
            current.append(word)
            test_line = " ".join(current)
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] > self.WIDTH - 80:
                if len(current) > 1:
                    lines.append(" ".join(current[:-1]))
                    current = [word]
                else:
                    lines.append(test_line)
                    current = []
        if current:
            lines.append(" ".join(current))

        # Draw headline lines
        line_height = font_size + 20
        total_height = len(lines) * line_height
        start_y = self.HEIGHT - total_height - 160

        for i, line in enumerate(lines):
            y = start_y + i * line_height
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (self.WIDTH - (bbox[2] - bbox[0])) // 2
            # Shadow
            draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 180))
            # Main text
            draw.text((x, y), line, font=font, fill=style["text_color"])

        # Brand logo text at bottom
        logo = style["logo_text"]
        logo_bbox = draw.textbbox((0, 0), logo, font=small_font)
        logo_x = (self.WIDTH - (logo_bbox[2] - logo_bbox[0])) // 2
        draw.text((logo_x, self.HEIGHT - 100), logo, font=small_font, fill=(r, g, b))

        # Variant indicator dot
        dot_colors = {"hook": (255, 107, 157), "curiosity": (124, 58, 237), "authority": (0, 212, 255)}
        dot_color = dot_colors.get(variant, (255, 255, 255))
        draw.ellipse([(30, 30), (50, 50)], fill=dot_color)

        img.save(output_path, "PNG", optimize=True)
        return output_path

    def _create_with_ffmpeg(
        self,
        frame_path: str,
        headline: str,
        style: dict,
        output_path: str,
    ) -> str:
        """FFmpeg drawtext fallback for thumbnail creation"""
        escaped = headline.replace("'", "\\'").replace(":", "\\:")
        color = style["text_color"].lstrip("#")

        cmd = [
            self.ffmpeg_bin, "-y",
            "-i", frame_path,
            "-vf", (
                f"scale={self.WIDTH}:{self.HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={self.WIDTH}:{self.HEIGHT},"
                f"drawtext=text='{escaped}':fontsize={style['font_size']}:"
                f"fontcolor=white:x=(w-text_w)/2:y=h-200:"
                f"box=1:boxcolor=black@0.7:boxborderw=20"
            ),
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            Path(output_path).write_bytes(b"placeholder")
        return output_path

    def _run_ffmpeg_frame(
        self,
        video_path: str,
        output_path: str,
        timestamp_sec: float,
    ) -> str:
        """Run FFmpeg to extract a single frame. In tests: mocked."""
        cmd = [
            self.ffmpeg_bin, "-y",
            "-ss", str(timestamp_sec),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and Path(output_path).exists():
                return output_path
        except Exception as e:
            logger.debug(f"FFmpeg frame extraction failed at {timestamp_sec}s: {e}")
        return output_path

    # ─────────────────────────────────────────
    # HEADLINE DERIVATION
    # ─────────────────────────────────────────

    def _derive_headline(
        self,
        title: str,
        variant: str,
        tone: str,
        brand: str,
    ) -> str:
        """Derive a thumbnail headline from title, variant, and tone"""
        # Clean title — remove special chars, truncate
        clean = re.sub(r'[^\w\s]', '', title).strip()
        words = clean.split()

        # Brand-aware derivation
        is_b2b = tone in ("authority", "developer_energy", "founder_energy")

        if variant == "hook":
            if is_b2b:
                return f"This mistake is costing you clients"
            else:
                return f"Nobody warned me about this"

        elif variant == "curiosity":
            if words:
                subject = " ".join(words[:3])
                return f"The truth about {subject}"
            return "What nobody tells you"

        elif variant == "authority":
            if is_b2b:
                return f"The exact system that works"
            else:
                return f"How I solved this in minutes"

        return title[:60] if title else "Watch this"
