"""
HezCast Engine — QA Validator Tests
TDD Phase 3 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

7-point post-render quality gate:
  resolution | duration | audio_sync | black_frames |
  subtitle_coverage | face_visible | file_size
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
def validator():
    from core.qa_validator import QAValidator
    return QAValidator()

@pytest.fixture
def valid_mp4(tmp_path):
    """Fake MP4 file with plausible size"""
    path = tmp_path / "video.mp4"
    # ~18MB fake MP4 (realistic size)
    path.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * (18 * 1024 * 1024 - 12))
    return path

@pytest.fixture
def valid_report():
    """A fully passing QA report"""
    return {
        "resolution_ok":      True,
        "duration_ok":        True,
        "audio_sync_ok":      True,
        "no_black_frames":    True,
        "subtitle_coverage":  0.96,
        "avatar_face_visible": True,
        "file_size_ok":       True,
        "overall_pass":       True,
        "failure_reasons":    [],
    }


# ─────────────────────────────────────────────
# QA REPORT STRUCTURE TESTS
# ─────────────────────────────────────────────

class TestQAReportStructure:

    def test_validate_returns_dict(self, validator, valid_mp4):
        """validate() must return a dict"""
        with patch.object(validator, '_check_resolution', return_value=(True, "1080x1920")):
            with patch.object(validator, '_check_duration', return_value=(True, 24.3)):
                with patch.object(validator, '_check_audio_sync', return_value=(True, 45.0)):
                    with patch.object(validator, '_check_black_frames', return_value=(True, 0)):
                        with patch.object(validator, '_check_subtitle_coverage', return_value=0.96):
                            with patch.object(validator, '_check_face_visible', return_value=(True, 0.94)):
                                result = validator.validate(
                                    video_path=str(valid_mp4),
                                    target_duration=25.0,
                                    subtitle_coverage=0.96
                                )
        assert isinstance(result, dict)

    def test_report_has_all_seven_checks(self, validator, valid_mp4):
        """Report must include all 7 QA check fields"""
        required = [
            "resolution_ok", "duration_ok", "audio_sync_ok",
            "no_black_frames", "subtitle_coverage",
            "avatar_face_visible", "file_size_ok"
        ]
        with patch.object(validator, '_check_resolution', return_value=(True, "1080x1920")):
            with patch.object(validator, '_check_duration', return_value=(True, 24.3)):
                with patch.object(validator, '_check_audio_sync', return_value=(True, 45.0)):
                    with patch.object(validator, '_check_black_frames', return_value=(True, 0)):
                        with patch.object(validator, '_check_subtitle_coverage', return_value=0.96):
                            with patch.object(validator, '_check_face_visible', return_value=(True, 0.94)):
                                report = validator.validate(
                                    video_path=str(valid_mp4),
                                    target_duration=25.0,
                                    subtitle_coverage=0.96
                                )
        for field in required:
            assert field in report, f"Report missing field: {field}"

    def test_report_has_overall_pass(self, validator, valid_mp4):
        """Report must have overall_pass boolean"""
        with patch.object(validator, '_check_resolution', return_value=(True, "1080x1920")):
            with patch.object(validator, '_check_duration', return_value=(True, 24.3)):
                with patch.object(validator, '_check_audio_sync', return_value=(True, 45.0)):
                    with patch.object(validator, '_check_black_frames', return_value=(True, 0)):
                        with patch.object(validator, '_check_subtitle_coverage', return_value=0.96):
                            with patch.object(validator, '_check_face_visible', return_value=(True, 0.94)):
                                report = validator.validate(
                                    video_path=str(valid_mp4),
                                    target_duration=25.0,
                                    subtitle_coverage=0.96
                                )
        assert "overall_pass" in report
        assert isinstance(report["overall_pass"], bool)

    def test_report_has_failure_reasons_list(self, validator, valid_mp4):
        """Report must have failure_reasons list"""
        with patch.object(validator, '_check_resolution', return_value=(True, "1080x1920")):
            with patch.object(validator, '_check_duration', return_value=(True, 24.3)):
                with patch.object(validator, '_check_audio_sync', return_value=(True, 45.0)):
                    with patch.object(validator, '_check_black_frames', return_value=(True, 0)):
                        with patch.object(validator, '_check_subtitle_coverage', return_value=0.96):
                            with patch.object(validator, '_check_face_visible', return_value=(True, 0.94)):
                                report = validator.validate(
                                    video_path=str(valid_mp4),
                                    target_duration=25.0,
                                    subtitle_coverage=0.96
                                )
        assert "failure_reasons" in report
        assert isinstance(report["failure_reasons"], list)


# ─────────────────────────────────────────────
# OVERALL PASS/FAIL LOGIC TESTS
# ─────────────────────────────────────────────

class TestOverallPassFail:

    def test_all_checks_pass_gives_overall_pass(self, validator, valid_report):
        """All checks True must give overall_pass=True"""
        assert validator.compute_overall_pass(valid_report) is True

    def test_one_check_fail_gives_overall_fail(self, validator, valid_report):
        """Any single check False must give overall_pass=False"""
        valid_report["resolution_ok"] = False
        assert validator.compute_overall_pass(valid_report) is False

    def test_multiple_checks_fail_gives_overall_fail(self, validator, valid_report):
        """Multiple failures must give overall_pass=False"""
        valid_report["duration_ok"] = False
        valid_report["audio_sync_ok"] = False
        assert validator.compute_overall_pass(valid_report) is False

    def test_low_subtitle_coverage_fails(self, validator, valid_report):
        """subtitle_coverage < 0.85 must cause overall fail"""
        valid_report["subtitle_coverage"] = 0.60
        assert validator.compute_overall_pass(valid_report) is False

    def test_adequate_subtitle_coverage_passes(self, validator, valid_report):
        """subtitle_coverage >= 0.85 must not fail on coverage alone"""
        valid_report["subtitle_coverage"] = 0.87
        assert validator.compute_overall_pass(valid_report) is True

    def test_failure_reasons_populated_on_fail(self, validator, valid_report):
        """failure_reasons must list what failed"""
        valid_report["resolution_ok"] = False
        valid_report["audio_sync_ok"] = False
        reasons = validator.get_failure_reasons(valid_report)
        assert isinstance(reasons, list)
        assert len(reasons) >= 2

    def test_failure_reasons_empty_on_pass(self, validator, valid_report):
        """failure_reasons must be empty when all checks pass"""
        reasons = validator.get_failure_reasons(valid_report)
        assert reasons == []


# ─────────────────────────────────────────────
# INDIVIDUAL CHECK TESTS
# ─────────────────────────────────────────────

class TestIndividualChecks:

    def test_file_size_check_passes_for_normal_video(self, validator, valid_mp4):
        """18MB MP4 must pass file size check"""
        ok, size = validator._check_file_size(str(valid_mp4))
        assert ok is True
        assert size > 0

    def test_file_size_check_fails_for_tiny_file(self, validator, tmp_path):
        """1KB file must fail file size check (too small)"""
        tiny = tmp_path / "tiny.mp4"
        tiny.write_bytes(b"\x00" * 1024)
        ok, size = validator._check_file_size(str(tiny))
        assert ok is False

    def test_file_size_check_fails_for_missing_file(self, validator):
        """Missing file must fail file size check"""
        ok, size = validator._check_file_size("/nonexistent/video.mp4")
        assert ok is False

    def test_duration_check_passes_within_tolerance(self, validator):
        """Duration within ±3s of target must pass"""
        ok, actual = validator._check_duration(
            actual_duration=24.3,
            target_duration=25.0,
            tolerance_sec=3.0
        )
        assert ok is True

    def test_duration_check_fails_outside_tolerance(self, validator):
        """Duration more than 3s from target must fail"""
        ok, actual = validator._check_duration(
            actual_duration=10.0,
            target_duration=25.0,
            tolerance_sec=3.0
        )
        assert ok is False

    def test_duration_check_exact_match_passes(self, validator):
        """Exact duration match must pass"""
        ok, actual = validator._check_duration(
            actual_duration=25.0,
            target_duration=25.0,
            tolerance_sec=3.0
        )
        assert ok is True

    def test_audio_sync_passes_under_100ms(self, validator):
        """Audio drift < 100ms must pass sync check"""
        ok, drift = validator._check_audio_sync(drift_ms=45.0)
        assert ok is True

    def test_audio_sync_fails_over_100ms(self, validator):
        """Audio drift >= 100ms must fail sync check"""
        ok, drift = validator._check_audio_sync(drift_ms=150.0)
        assert ok is False

    def test_subtitle_coverage_passes_above_threshold(self, validator):
        """Coverage >= 0.85 must pass"""
        result = validator._check_subtitle_coverage(coverage=0.92)
        assert result >= 0.85

    def test_validate_nonexistent_file_raises(self, validator):
        """validate() on missing file must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            validator.validate(
                video_path="/nonexistent/video.mp4",
                target_duration=25.0,
                subtitle_coverage=0.96
            )


# ─────────────────────────────────────────────
# RETRY LOGIC TESTS
# ─────────────────────────────────────────────

class TestRetryLogic:

    def test_should_retry_returns_true_on_first_failure(self, validator):
        """First failure should trigger retry"""
        assert validator.should_retry(attempt=1) is True

    def test_should_retry_returns_false_on_second_failure(self, validator):
        """Second failure should not trigger retry (max 1 retry)"""
        assert validator.should_retry(attempt=2) is False

    def test_should_retry_false_on_pass(self, validator, valid_report):
        """Passing report must not trigger retry"""
        assert validator.should_retry(attempt=1, report=valid_report) is False

    def test_max_retries_is_one(self, validator):
        """MAX_RETRIES must be exactly 1"""
        assert validator.MAX_RETRIES == 1
