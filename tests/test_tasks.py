"""
HezCast Engine — Celery Pipeline Task Tests
TDD Phase 4 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

Pipeline task chain:
  generate_hooks → await_selection → synthesize_voice →
  select_clip → compose_video → generate_subtitles → qa_check → finalize
"""

import pytest
import uuid
from unittest.mock import patch, MagicMock, call


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def job_id():
    return str(uuid.uuid4())

@pytest.fixture
def base_job(job_id):
    return {
        "job_id":  job_id,
        "brand":   "GiftMode",
        "topic":   "forgot birthday gift",
        "tone":    "emotional",
        "status":  "queued",
    }

@pytest.fixture
def mock_script():
    return {
        "hook":      "Nobody told me you could forget TWICE...",
        "problem":   "Two hours. Zero ideas. Full guilt trip.",
        "agitate":   "I opened Amazon. 847 options. Closed it.",
        "solution":  "GiftMode gave me 3 ideas in 9 seconds.",
        "proof":     "500K people use it. Free.",
        "cta":       "Download GiftMode. Before you forget again.",
        "full_script": "Nobody told me you could forget TWICE...",
        "word_count": 68,
        "estimated_duration_sec": 26.0,
        "llm_used": "claude",
    }

@pytest.fixture
def mock_hooks():
    return [
        {"variant_num": 1, "hook_text": "Nobody told me you could forget TWICE...", "full_script": "...", "selected": False},
        {"variant_num": 2, "hook_text": "I had 2 hours and zero ideas.", "full_script": "...", "selected": False},
        {"variant_num": 3, "hook_text": "POV: Her birthday is TODAY.", "full_script": "...", "selected": False},
        {"variant_num": 4, "hook_text": "The gift panic is real.", "full_script": "...", "selected": False},
        {"variant_num": 5, "hook_text": "She said it's fine. It wasn't.", "full_script": "...", "selected": False},
    ]

@pytest.fixture
def mock_clip():
    return {
        "id": "pexels_1234",
        "local_path": "/storage/clips/pexels_1234.mp4",
        "score": 0.87,
        "duration_sec": 25.0,
        "tags": ["happy", "celebration"],
    }

@pytest.fixture
def mock_qa_pass():
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

@pytest.fixture
def mock_qa_fail():
    return {
        "resolution_ok":      True,
        "duration_ok":        False,
        "audio_sync_ok":      True,
        "no_black_frames":    True,
        "subtitle_coverage":  0.96,
        "avatar_face_visible": True,
        "file_size_ok":       True,
        "overall_pass":       False,
        "failure_reasons":    ["Duration out of range: 10.0s (tolerance ±3.0s)"],
    }


# ─────────────────────────────────────────────
# TASK: GENERATE HOOKS
# ─────────────────────────────────────────────

class TestGenerateHooksTask:

    def test_generate_hooks_returns_job_id(self, base_job, mock_hooks):
        """generate_hooks_task must return the job_id"""
        from workers.tasks import generate_hooks_task
        with patch("workers.tasks.HookGenerator") as MockGen:
            MockGen.return_value.generate.return_value = mock_hooks
            with patch("workers.tasks.update_job_status"):
                with patch("workers.tasks.save_hook_variants"):
                    result = generate_hooks_task(base_job)
        assert result["job_id"] == base_job["job_id"]

    def test_generate_hooks_sets_status_awaiting(self, base_job, mock_hooks):
        """After hook generation, status must be awaiting_selection"""
        from workers.tasks import generate_hooks_task
        with patch("workers.tasks.HookGenerator") as MockGen:
            MockGen.return_value.generate.return_value = mock_hooks
            with patch("workers.tasks.update_job_status") as mock_update:
                with patch("workers.tasks.save_hook_variants"):
                    generate_hooks_task(base_job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "awaiting_selection" in calls

    def test_generate_hooks_saves_variants(self, base_job, mock_hooks):
        """Hook variants must be saved to DB"""
        from workers.tasks import generate_hooks_task
        with patch("workers.tasks.HookGenerator") as MockGen:
            MockGen.return_value.generate.return_value = mock_hooks
            with patch("workers.tasks.update_job_status"):
                with patch("workers.tasks.save_hook_variants") as mock_save:
                    generate_hooks_task(base_job)
        assert mock_save.called

    def test_generate_hooks_on_error_sets_failed_status(self, base_job):
        """On exception, status must be set to failed"""
        from workers.tasks import generate_hooks_task
        with patch("workers.tasks.HookGenerator") as MockGen:
            MockGen.return_value.generate.side_effect = Exception("LLM error")
            with patch("workers.tasks.update_job_status") as mock_update:
                with patch("workers.tasks.save_hook_variants"):
                    result = generate_hooks_task(base_job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in calls


# ─────────────────────────────────────────────
# TASK: SYNTHESIZE VOICE
# ─────────────────────────────────────────────

class TestSynthesizeVoiceTask:

    def test_voice_task_returns_voice_path(self, base_job):
        """synthesize_voice_task must return voice_path in result"""
        from workers.tasks import synthesize_voice_task
        job = {**base_job, "selected_script": "Test script text here"}
        with patch("workers.tasks.VoiceEngine") as MockVoice:
            MockVoice.return_value.synthesize.return_value = "/storage/inputs/job/voice.wav"
            with patch("workers.tasks.update_job_status"):
                result = synthesize_voice_task(job)
        assert "voice_path" in result
        assert result["voice_path"].endswith(".wav")

    def test_voice_task_calls_synthesize_once(self, base_job):
        """VoiceEngine.synthesize must be called exactly once"""
        from workers.tasks import synthesize_voice_task
        job = {**base_job, "selected_script": "Test script"}
        with patch("workers.tasks.VoiceEngine") as MockVoice:
            instance = MockVoice.return_value
            instance.synthesize.return_value = "/storage/inputs/job/voice.wav"
            with patch("workers.tasks.update_job_status"):
                synthesize_voice_task(job)
        assert instance.synthesize.call_count == 1

    def test_voice_task_passes_correct_brand(self, base_job):
        """synthesize must be called with the correct brand"""
        from workers.tasks import synthesize_voice_task
        job = {**base_job, "selected_script": "Test script"}
        captured_kwargs = {}
        def capture_call(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return "/storage/inputs/job/voice.wav"
        with patch("workers.tasks.VoiceEngine") as MockVoice:
            MockVoice.return_value.synthesize.side_effect = capture_call
            with patch("workers.tasks.update_job_status"):
                synthesize_voice_task(job)
        assert captured_kwargs.get("brand") == "GiftMode"

    def test_voice_task_on_error_sets_failed(self, base_job):
        """On TTS error, status must be set to failed"""
        from workers.tasks import synthesize_voice_task
        job = {**base_job, "selected_script": "Test"}
        with patch("workers.tasks.VoiceEngine") as MockVoice:
            MockVoice.return_value.synthesize.side_effect = Exception("TTS error")
            with patch("workers.tasks.update_job_status") as mock_update:
                synthesize_voice_task(job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in calls


# ─────────────────────────────────────────────
# TASK: SELECT CLIP
# ─────────────────────────────────────────────

class TestSelectClipTask:

    def test_clip_task_returns_clip_path(self, base_job, mock_clip):
        """select_clip_task must return bg_clip_path"""
        from workers.tasks import select_clip_task
        job = {**base_job, "selected_script": "birthday gift forgotten panic"}
        with patch("workers.tasks.ClipSelector") as MockClip:
            MockClip.return_value.select_best.return_value = mock_clip
            with patch("workers.tasks.update_job_status"):
                result = select_clip_task(job)
        assert "bg_clip_path" in result

    def test_clip_task_passes_brand(self, base_job, mock_clip):
        """select_best must be called with the correct brand"""
        from workers.tasks import select_clip_task
        job = {**base_job, "selected_script": "birthday gift"}
        captured = {}
        def capture(*args, **kwargs):
            captured.update(kwargs)
            return mock_clip
        with patch("workers.tasks.ClipSelector") as MockClip:
            MockClip.return_value.select_best.side_effect = capture
            with patch("workers.tasks.update_job_status"):
                select_clip_task(job)
        assert captured.get("brand") == "GiftMode"

    def test_clip_task_on_error_does_not_fail_job(self, base_job):
        """Clip selection failure must not fail the job (use color bg instead)"""
        from workers.tasks import select_clip_task
        job = {**base_job, "selected_script": "test"}
        with patch("workers.tasks.ClipSelector") as MockClip:
            MockClip.return_value.select_best.side_effect = Exception("No clips")
            with patch("workers.tasks.update_job_status"):
                result = select_clip_task(job)
        # Job must continue — bg_clip_path may be None (FFmpeg uses color bg)
        assert "job_id" in result


# ─────────────────────────────────────────────
# TASK: COMPOSE VIDEO
# ─────────────────────────────────────────────

class TestComposeVideoTask:

    def test_compose_task_returns_output_path(self, base_job, tmp_path):
        """compose_video_task must return output_path"""
        from workers.tasks import compose_video_task
        job = {
            **base_job,
            "voice_path":   "/storage/inputs/job/voice.wav",
            "bg_clip_path": "/storage/clips/pexels_1234.mp4",
        }
        fake_output = str(tmp_path / "final.mp4")
        with patch("workers.tasks.VideoComposer") as MockComposer:
            MockComposer.return_value.compose.return_value = fake_output
            with patch("workers.tasks.update_job_status"):
                with patch("workers.tasks.generate_subs_task"):
                    result = compose_video_task(job)
        assert "output_path" in result
        assert result["output_path"].endswith("final.mp4")

    def test_compose_task_sets_composing_status(self, base_job, tmp_path):
        """Status must be set to composing during task"""
        from workers.tasks import compose_video_task
        job = {**base_job, "voice_path": "/storage/inputs/job/voice.wav"}
        with patch("workers.tasks.VideoComposer") as MockComposer:
            MockComposer.return_value.compose.return_value = str(tmp_path / "out.mp4")
            with patch("workers.tasks.update_job_status") as mock_update:
                with patch("workers.tasks.generate_subs_task"):
                    compose_video_task(job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "composing" in calls

    def test_compose_task_on_error_sets_failed(self, base_job):
        """On FFmpeg error, status must be set to failed"""
        from workers.tasks import compose_video_task
        job = {**base_job, "voice_path": "/storage/inputs/job/voice.wav"}
        with patch("workers.tasks.VideoComposer") as MockComposer:
            MockComposer.return_value.compose.side_effect = Exception("FFmpeg error")
            with patch("workers.tasks.update_job_status") as mock_update:
                compose_video_task(job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "failed" in calls


# ─────────────────────────────────────────────
# TASK: QA CHECK
# ─────────────────────────────────────────────

class TestQACheckTask:

    def test_qa_task_passes_sets_completed(self, base_job, mock_qa_pass, tmp_path):
        """Passing QA must set status to completed"""
        from workers.tasks import qa_check_task
        fake_mp4 = tmp_path / "final.mp4"
        fake_mp4.write_bytes(b"\x00" * (10 * 1024 * 1024))
        job = {**base_job, "output_path": str(fake_mp4), "duration_sec": 25.0}
        with patch("workers.tasks.QAValidator") as MockQA:
            MockQA.return_value.validate.return_value = mock_qa_pass
            with patch("workers.tasks.update_job_status") as mock_update:
                with patch("workers.tasks.save_qa_report"):
                    qa_check_task(job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "completed" in calls

    def test_qa_task_first_fail_retries(self, base_job, mock_qa_fail, tmp_path):
        """First QA failure must trigger retry"""
        from workers.tasks import qa_check_task
        fake_mp4 = tmp_path / "final.mp4"
        fake_mp4.write_bytes(b"\x00" * (10 * 1024 * 1024))
        job = {**base_job, "output_path": str(fake_mp4), "duration_sec": 25.0, "retry_count": 0}
        with patch("workers.tasks.QAValidator") as MockQA:
            MockQA.return_value.validate.return_value = mock_qa_fail
            with patch("workers.tasks.update_job_status"):
                with patch("workers.tasks.save_qa_report"):
                    with patch("workers.tasks.compose_video_task") as mock_retry:
                        qa_check_task(job)
        assert mock_retry.called

    def test_qa_task_second_fail_sets_needs_review(self, base_job, mock_qa_fail, tmp_path):
        """Second QA failure must set status to needs_review"""
        from workers.tasks import qa_check_task
        fake_mp4 = tmp_path / "final.mp4"
        fake_mp4.write_bytes(b"\x00" * (10 * 1024 * 1024))
        job = {**base_job, "output_path": str(fake_mp4), "duration_sec": 25.0, "retry_count": 1}
        with patch("workers.tasks.QAValidator") as MockQA:
            MockQA.return_value.validate.return_value = mock_qa_fail
            MockQA.return_value.should_retry.return_value = False
            with patch("workers.tasks.update_job_status") as mock_update:
                with patch("workers.tasks.save_qa_report"):
                    with patch("workers.tasks.compose_video_task"):
                        qa_check_task(job)
        calls = [c[0][1] for c in mock_update.call_args_list]
        assert "needs_review" in calls

    def test_qa_task_saves_report(self, base_job, mock_qa_pass, tmp_path):
        """QA report must always be saved regardless of outcome"""
        from workers.tasks import qa_check_task
        fake_mp4 = tmp_path / "final.mp4"
        fake_mp4.write_bytes(b"\x00" * (10 * 1024 * 1024))
        job = {**base_job, "output_path": str(fake_mp4), "duration_sec": 25.0}
        with patch("workers.tasks.QAValidator") as MockQA:
            MockQA.return_value.validate.return_value = mock_qa_pass
            with patch("workers.tasks.update_job_status"):
                with patch("workers.tasks.save_qa_report") as mock_save:
                    qa_check_task(job)
        assert mock_save.called
