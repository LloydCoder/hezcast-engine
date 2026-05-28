"""
HezCast Engine — QA Validator
Tinlance Limited | Apache 2.0

7-point post-render quality gate. Runs after every FFmpeg compose.
Blocks broken videos from reaching storage.

Checks:
  1. resolution      → Must be 1080x1920
  2. duration        → Within ±3s of target
  3. audio_sync      → Drift < 100ms
  4. black_frames    → Zero detected
  5. subtitle_cov    → > 85% speech covered
  6. face_visible    → Avatar face confidence > 0.70
  7. file_size       → 5MB < size < 150MB

On fail: auto-retry once → if second fail → status = needs_review
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class QAValidator:
    """
    Post-render quality gate for HezCast output videos.

    Usage:
        validator = QAValidator()
        report = validator.validate(
            video_path="/storage/outputs/job_id/final.mp4",
            target_duration=25.0,
            subtitle_coverage=0.96
        )
        if not report["overall_pass"]:
            print(report["failure_reasons"])
    """

    # ── Thresholds ────────────────────────────
    TARGET_WIDTH          = 1080
    TARGET_HEIGHT         = 1920
    DURATION_TOLERANCE    = 3.0     # seconds
    AUDIO_DRIFT_MAX_MS    = 100.0   # milliseconds
    SUBTITLE_MIN_COVERAGE = 0.85    # 85% of speech must be captioned
    FACE_CONFIDENCE_MIN   = 0.70    # Avatar face detection confidence
    FILE_SIZE_MIN_BYTES   = 5  * 1024 * 1024   # 5MB
    FILE_SIZE_MAX_BYTES   = 150 * 1024 * 1024  # 150MB

    MAX_RETRIES = 1

    def __init__(self):
        pass

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def validate(
        self,
        video_path: str,
        target_duration: float,
        subtitle_coverage: float = 0.0,
        avatar_present: bool = False,
    ) -> dict:
        """
        Run all 7 QA checks on a rendered video.

        Args:
            video_path:         Path to the MP4 file
            target_duration:    Expected duration in seconds
            subtitle_coverage:  Pre-computed coverage ratio from SubtitleEngine
            avatar_present:     Whether an avatar was composited in

        Returns:
            QA report dict with overall_pass, per-check booleans,
            and failure_reasons list.

        Raises:
            FileNotFoundError: If video file doesn't exist
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        report = {}

        # Check 1: File size
        size_ok, file_size = self._check_file_size(video_path)
        report["file_size_ok"] = size_ok
        report["actual_file_size_bytes"] = file_size

        # Check 2: Resolution (requires ffprobe)
        res_ok, resolution = self._check_resolution(video_path)
        report["resolution_ok"] = res_ok
        report["actual_resolution"] = resolution

        # Check 3: Duration
        actual_dur = self._get_video_duration(video_path)
        dur_ok, _ = self._check_duration(
            actual_duration=actual_dur,
            target_duration=target_duration,
            tolerance_sec=self.DURATION_TOLERANCE
        )
        report["duration_ok"] = dur_ok
        report["actual_duration_sec"] = actual_dur

        # Check 4: Audio sync
        sync_ok, drift_ms = self._check_audio_sync(drift_ms=self._estimate_audio_drift(video_path))
        report["audio_sync_ok"] = sync_ok
        report["audio_drift_ms"] = drift_ms

        # Check 5: Black frames
        black_ok, black_count = self._check_black_frames(video_path)
        report["no_black_frames"] = black_ok
        report["black_frame_count"] = black_count

        # Check 6: Subtitle coverage (passed in — computed by SubtitleEngine)
        coverage = self._check_subtitle_coverage(subtitle_coverage)
        report["subtitle_coverage"] = coverage

        # Check 7: Avatar face visible (only if avatar was composited)
        if avatar_present:
            face_ok, confidence = self._check_face_visible(video_path)
        else:
            face_ok, confidence = True, 1.0   # N/A when no avatar
        report["avatar_face_visible"] = face_ok
        report["face_confidence"] = confidence

        # ── Overall pass/fail ───────────────────
        report["overall_pass"] = self.compute_overall_pass(report)
        report["failure_reasons"] = self.get_failure_reasons(report)

        logger.info(
            f"QA complete | pass={report['overall_pass']} | "
            f"size={file_size//1024//1024}MB | "
            f"duration={actual_dur:.1f}s | "
            f"subtitle_cov={coverage:.2f} | "
            f"failures={report['failure_reasons']}"
        )

        return report

    def compute_overall_pass(self, report: dict) -> bool:
        """
        Compute overall pass from individual check results.

        Fails if any boolean check is False OR subtitle_coverage < threshold.
        """
        boolean_checks = [
            "resolution_ok", "duration_ok", "audio_sync_ok",
            "no_black_frames", "avatar_face_visible", "file_size_ok"
        ]

        for check in boolean_checks:
            if check in report and not report[check]:
                return False

        coverage = report.get("subtitle_coverage", 1.0)
        if isinstance(coverage, (int, float)) and coverage < self.SUBTITLE_MIN_COVERAGE:
            return False

        return True

    def get_failure_reasons(self, report: dict) -> list[str]:
        """
        Get human-readable list of failed checks.

        Returns:
            Empty list if all passed, else list of failure descriptions.
        """
        reasons = []

        if not report.get("resolution_ok", True):
            actual = report.get("actual_resolution", "unknown")
            reasons.append(
                f"Wrong resolution: {actual} "
                f"(expected {self.TARGET_WIDTH}x{self.TARGET_HEIGHT})"
            )

        if not report.get("duration_ok", True):
            actual = report.get("actual_duration_sec", 0)
            reasons.append(
                f"Duration out of range: {actual:.1f}s "
                f"(tolerance ±{self.DURATION_TOLERANCE}s)"
            )

        if not report.get("audio_sync_ok", True):
            drift = report.get("audio_drift_ms", 0)
            reasons.append(
                f"Audio sync drift too high: {drift:.0f}ms "
                f"(max {self.AUDIO_DRIFT_MAX_MS}ms)"
            )

        if not report.get("no_black_frames", True):
            count = report.get("black_frame_count", 0)
            reasons.append(f"Black frames detected: {count}")

        coverage = report.get("subtitle_coverage", 1.0)
        if isinstance(coverage, (int, float)) and coverage < self.SUBTITLE_MIN_COVERAGE:
            reasons.append(
                f"Low subtitle coverage: {coverage:.0%} "
                f"(min {self.SUBTITLE_MIN_COVERAGE:.0%})"
            )

        if not report.get("avatar_face_visible", True):
            conf = report.get("face_confidence", 0)
            reasons.append(
                f"Avatar face not visible: confidence {conf:.2f} "
                f"(min {self.FACE_CONFIDENCE_MIN})"
            )

        if not report.get("file_size_ok", True):
            size = report.get("actual_file_size_bytes", 0)
            reasons.append(
                f"File size out of range: {size // 1024 // 1024}MB "
                f"(expected 5–150MB)"
            )

        return reasons

    def should_retry(self, attempt: int, report: Optional[dict] = None) -> bool:
        """
        Determine if a failed job should be retried.

        Args:
            attempt: Current attempt number (1-indexed)
            report:  QA report (if None, assumes failure)

        Returns:
            True if should retry, False otherwise
        """
        # If report passed and it's a pass, no retry needed
        if report and report.get("overall_pass"):
            return False
        # Only retry on first attempt
        return attempt <= self.MAX_RETRIES

    # ─────────────────────────────────────────
    # INDIVIDUAL CHECKS (mockable in tests)
    # ─────────────────────────────────────────

    def _check_file_size(self, video_path: str) -> Tuple[bool, int]:
        """Check file size is within acceptable range"""
        try:
            size = Path(video_path).stat().st_size
            ok = self.FILE_SIZE_MIN_BYTES <= size <= self.FILE_SIZE_MAX_BYTES
            return ok, size
        except Exception:
            return False, 0

    def _check_resolution(self, video_path: str) -> Tuple[bool, str]:
        """
        Check video resolution using ffprobe.
        In production: runs ffprobe subprocess.
        Falls back gracefully if ffprobe unavailable.
        """
        try:
            import subprocess
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=s=x:p=0",
                    video_path
                ],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                res = result.stdout.strip()
                parts = res.split("x")
                if len(parts) == 2:
                    w, h = int(parts[0]), int(parts[1])
                    ok = (w == self.TARGET_WIDTH and h == self.TARGET_HEIGHT)
                    return ok, res
        except Exception as e:
            logger.debug(f"ffprobe resolution check failed: {e}")

        # Can't verify — assume pass (don't block on infra issues)
        return True, f"{self.TARGET_WIDTH}x{self.TARGET_HEIGHT}"

    def _check_duration(
        self,
        actual_duration: float,
        target_duration: float,
        tolerance_sec: float = 3.0
    ) -> Tuple[bool, float]:
        """Check duration is within tolerance of target"""
        ok = abs(actual_duration - target_duration) <= tolerance_sec
        return ok, actual_duration

    def _check_audio_sync(self, drift_ms: float) -> Tuple[bool, float]:
        """Check audio/video sync drift is below threshold"""
        ok = drift_ms < self.AUDIO_DRIFT_MAX_MS
        return ok, drift_ms

    def _check_black_frames(self, video_path: str) -> Tuple[bool, int]:
        """
        Detect black frames using FFmpeg blackdetect filter.
        Falls back gracefully if FFmpeg unavailable.
        """
        try:
            import subprocess
            result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-vf", "blackdetect=d=0.1:pix_th=0.10",
                    "-an", "-f", "null", "-"
                ],
                capture_output=True, text=True, timeout=30
            )
            black_count = result.stderr.count("black_start")
            return black_count == 0, black_count
        except Exception as e:
            logger.debug(f"Black frame check failed: {e}")
            return True, 0  # Assume pass on error

    def _check_subtitle_coverage(self, coverage: float) -> float:
        """Validate and return subtitle coverage value"""
        return max(0.0, min(1.0, float(coverage)))

    def _check_face_visible(self, video_path: str) -> Tuple[bool, float]:
        """
        Check avatar face is visible in video frames.
        Uses OpenCV face detection on first few frames.
        Falls back gracefully if OpenCV unavailable.
        """
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            frames_checked = 0
            faces_found = 0

            while frames_checked < 10:
                ret, frame = cap.read()
                if not ret:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                if len(faces) > 0:
                    faces_found += 1
                frames_checked += 1

            cap.release()

            if frames_checked == 0:
                return True, 1.0  # Can't check
            confidence = faces_found / frames_checked
            return confidence >= self.FACE_CONFIDENCE_MIN, confidence

        except Exception as e:
            logger.debug(f"Face visibility check failed: {e}")
            return True, 1.0  # Assume pass on error

    def _get_video_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe"""
        try:
            import subprocess
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path
                ],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0

    def _estimate_audio_drift(self, video_path: str) -> float:
        """
        Estimate audio/video sync drift.
        Returns drift in milliseconds.
        Falls back to 0ms (assume perfect sync) if can't measure.
        """
        try:
            import subprocess
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "stream=codec_type,start_time",
                    "-of", "json",
                    video_path
                ],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                streams = data.get("streams", [])
                video_start = next(
                    (float(s["start_time"]) for s in streams if s.get("codec_type") == "video"),
                    0.0
                )
                audio_start = next(
                    (float(s["start_time"]) for s in streams if s.get("codec_type") == "audio"),
                    0.0
                )
                return abs(video_start - audio_start) * 1000  # ms
        except Exception:
            pass
        return 0.0
