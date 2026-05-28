"""
HezCast Engine — Voice Engine
Tinlance Limited | Apache 2.0

Converts script text → brand-voiced WAV audio using Piper TTS.

Each brand has a distinct voice profile:
  GiftMode  → Maya   (warm, emotional, slightly fast)
  Tinlance  → Lloyd  (calm, authoritative, measured)
  WebTemify → Dev    (energetic, fast, direct)

In Docker: uses actual Piper TTS binary + .onnx voice models
In tests:  _run_tts is mocked — full interface tested without GPU
"""

import json
import logging
import os
import struct
import subprocess
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# VOICE ENGINE
# ─────────────────────────────────────────────

class VoiceEngine:
    """
    Converts script text into branded WAV audio via Piper TTS.

    Usage:
        engine = VoiceEngine()
        output_path = engine.synthesize(
            text="Nobody told me you could forget twice...",
            brand="GiftMode",
            output_path="/storage/inputs/job_abc/voice.wav"
        )
        duration = engine.estimate_duration(text, brand="GiftMode")
    """

    # Base words-per-second at speed=1.0
    # Piper TTS English average speaking pace
    BASE_WPS = 2.5

    # Per-brand voice profiles
    VOICE_PROFILES = {
        "GiftMode": {
            "model_id":    "en_US-lessac-medium",
            "description": "Maya — warm, relatable, emotional UGC female voice",
            "speed":       1.05,
            "sample_rate": 22050,
            "noise_scale": 0.667,
            "noise_w":     0.8,
            "onnx_path":   "config/voices/giftmode.onnx",
        },
        "Tinlance": {
            "model_id":    "en_US-ryan-medium",
            "description": "Lloyd — calm, authoritative, measured male voice",
            "speed":       0.97,
            "sample_rate": 22050,
            "noise_scale": 0.333,
            "noise_w":     0.6,
            "onnx_path":   "config/voices/tinlance.onnx",
        },
        "WebTemify": {
            "model_id":    "en_US-arctic-medium",
            "description": "Dev — fast, energetic, developer-energy male voice",
            "speed":       1.10,
            "sample_rate": 22050,
            "noise_scale": 0.5,
            "noise_w":     0.7,
            "onnx_path":   "config/voices/webtemify.onnx",
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "brands.json"

        with open(config_path) as f:
            self.brand_config = json.load(f)

        # Piper binary location (set in Docker environment)
        self.piper_bin = os.getenv("PIPER_BIN", "piper")
        self.project_root = Path(__file__).parent.parent

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        brand: str,
        output_path: str
    ) -> str:
        """
        Convert text to speech using the brand's voice profile.

        Args:
            text:        The script text to synthesize
            brand:       Brand name (GiftMode | Tinlance | WebTemify)
            output_path: Full path for the output WAV file

        Returns:
            output_path (str) on success

        Raises:
            ValueError: If text is empty or brand is unknown
            VoiceSynthesisError: If TTS subprocess fails
        """
        self._validate_inputs(text, brand)

        profile = self.get_voice_profile(brand)
        output_path = str(output_path)

        # Ensure parent directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Synthesizing voice | brand={brand} | "
            f"words={len(text.split())} | "
            f"speed={profile['speed']} | output={output_path}"
        )

        self._run_tts(text, output_path, profile)

        if not self.validate_wav(output_path):
            raise VoiceSynthesisError(
                f"TTS produced invalid WAV output: {output_path}"
            )

        duration = self._get_wav_duration(output_path)
        logger.info(f"Voice synthesis complete | duration={duration:.1f}s")

        return output_path

    def estimate_duration(self, text: str, brand: str) -> float:
        """
        Estimate audio duration from text length and brand voice speed.

        Args:
            text:  The script text
            brand: Brand name for speed profile lookup

        Returns:
            Estimated duration in seconds (float)
        """
        profile = self.get_voice_profile(brand)
        word_count = len(text.split())
        effective_wps = self.BASE_WPS * profile["speed"]
        return round(word_count / effective_wps, 1)

    def validate_wav(self, path: str) -> bool:
        """
        Validate that a WAV file exists and contains audio data.

        Returns:
            True if valid, False otherwise (never raises)
        """
        try:
            p = Path(path)
            if not p.exists():
                return False
            if p.stat().st_size == 0:
                return False

            with wave.open(path, 'r') as wav:
                if wav.getnframes() == 0:
                    return False
                if wav.getsampwidth() == 0:
                    return False
            return True

        except Exception as e:
            logger.debug(f"WAV validation failed for {path}: {e}")
            return False

    def get_voice_profile(self, brand: str) -> dict:
        """
        Get the voice profile for a brand.

        Raises:
            ValueError: If brand is unknown
        """
        if brand not in self.VOICE_PROFILES:
            available = list(self.VOICE_PROFILES.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available: {available}"
            )
        return self.VOICE_PROFILES[brand].copy()

    # ─────────────────────────────────────────
    # TTS RUNNER (mockable in tests)
    # ─────────────────────────────────────────

    def _run_tts(self, text: str, output_path: str, profile: dict) -> None:
        """
        Run Piper TTS subprocess to generate WAV.

        In production: calls `piper` binary with voice model.
        In tests: this method is mocked.

        Piper CLI usage:
            echo "text" | piper --model model.onnx --output_file out.wav
        """
        onnx_path = self.project_root / profile["onnx_path"]

        if not onnx_path.exists():
            logger.warning(
                f"Voice model not found: {onnx_path}. "
                f"Using fallback synthesis."
            )
            self._run_tts_fallback(text, output_path, profile)
            return

        # Build Piper config JSON (length_scale = 1/speed)
        length_scale = round(1.0 / profile["speed"], 3)
        piper_config = json.dumps({
            "length_scale": length_scale,
            "noise_scale": profile.get("noise_scale", 0.667),
            "noise_w": profile.get("noise_w", 0.8),
        })

        cmd = [
            self.piper_bin,
            "--model", str(onnx_path),
            "--output_file", output_path,
            "--json-input",
        ]

        input_json = json.dumps({
            "text": text,
            "speaker_id": 0,
            "output_file": output_path,
            **json.loads(piper_config)
        })

        try:
            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                raise VoiceSynthesisError(
                    f"Piper TTS failed (code {result.returncode}): "
                    f"{result.stderr[:300]}"
                )
        except subprocess.TimeoutExpired:
            raise VoiceSynthesisError("Piper TTS timed out after 120s")
        except FileNotFoundError:
            logger.warning("Piper binary not found. Using fallback synthesis.")
            self._run_tts_fallback(text, output_path, profile)

    def _run_tts_fallback(self, text: str, output_path: str, profile: dict) -> None:
        """
        Fallback TTS when Piper binary/model unavailable.
        Generates a silent WAV placeholder with correct duration.
        Used in development environments without Piper installed.
        """
        logger.warning(
            f"Using silent WAV fallback for: {output_path}. "
            f"Install Piper TTS for real voice output."
        )
        sample_rate = profile["sample_rate"]
        estimated_duration = self.estimate_duration(text, brand=self._brand_from_profile(profile))
        num_frames = int(sample_rate * estimated_duration)

        with wave.open(output_path, 'w') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            # Very quiet tone (not pure silence — Whisper needs some signal)
            frames = struct.pack(
                '<' + 'h' * num_frames,
                *([50] * num_frames)
            )
            wav.writeframes(frames)

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────

    def _brand_from_profile(self, profile: dict) -> str:
        """Reverse lookup brand name from profile dict"""
        for brand, p in self.VOICE_PROFILES.items():
            if p["model_id"] == profile.get("model_id"):
                return brand
        return "GiftMode"  # safe default

    def _get_wav_duration(self, path: str) -> float:
        """Get duration of a WAV file in seconds"""
        try:
            with wave.open(path, 'r') as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                return frames / float(rate)
        except Exception:
            return 0.0

    def _validate_inputs(self, text: str, brand: str) -> None:
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")
        if brand not in self.VOICE_PROFILES:
            available = list(self.VOICE_PROFILES.keys())
            raise ValueError(
                f"Unknown brand: '{brand}'. Available: {available}"
            )


# ─────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────

class VoiceSynthesisError(Exception):
    """Raised when TTS synthesis fails"""
    pass
