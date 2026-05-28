"""
HezCast Engine — Celery Pipeline Tasks
Tinlance Limited | Apache 2.0

Complete pipeline task chain:

  generate_hooks_task        → generates 3-5 hook variants, saves to store
        ↓ (user selects hook via API)
  synthesize_voice_task      → Piper TTS → voice.wav
        ↓
  select_clip_task           → CLIP+FAISS → best background clip
        ↓
  compose_video_task         → FFmpeg → raw_render.mp4
        ↓
  generate_subs_task         → faster-whisper → subtitles.ass
        ↓
  qa_check_task              → 7-point QA → pass/retry/needs_review
        ↓
  [completed]                → output_path available via GET /status/{job_id}

Each task:
  1. Updates job status in store
  2. Executes its core module
  3. Passes enriched job dict to next task
  4. Handles errors gracefully — sets failed status with message
"""

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Try to import Celery app — graceful fallback if Redis not available
try:
    from workers.celery_app import app
    CELERY_AVAILABLE = True
except Exception:
    CELERY_AVAILABLE = False
    class _MockApp:
        def task(self, *args, **kwargs):
            def decorator(fn):
                fn.delay = fn
                return fn
            return decorator
    app = _MockApp()

# ── Shared job/hooks store
from api.routes.generate import _jobs, _hooks_store

# ── Core module imports (top-level for testability)
from core.hook_generator import HookGenerator
from core.voice_engine import VoiceEngine
from core.clip_selector import ClipSelector
from core.video_composer import VideoComposer
from core.subtitle_engine import SubtitleEngine
from core.qa_validator import QAValidator
from core.post_generator import PostGenerator
from core.telegram_publisher import TelegramPublisher
from core.thumbnail_engine import ThumbnailEngine
from core.url_preprocessor import URLPreprocessor
from core.storage_lifecycle import StorageLifecycle


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def update_job_status(job_id: str, status: str, **kwargs) -> None:
    """Update job status and any additional fields in the job store"""
    if job_id in _jobs:
        _jobs[job_id]["status"] = status
        _jobs[job_id].update(kwargs)
    logger.info(f"Job {job_id[:8]}... → {status}")


def save_hook_variants(job_id: str, variants: list) -> None:
    """Persist hook variants to store"""
    _hooks_store[job_id] = variants


def save_qa_report(job_id: str, report: dict) -> None:
    """Persist QA report to job store"""
    if job_id in _jobs:
        _jobs[job_id]["qa_report"] = report
        _jobs[job_id]["qa_passed"] = report.get("overall_pass", False)


def _storage_path(job_id: str, filename: str) -> str:
    """Build storage path for job artifacts"""
    base = os.getenv("STORAGE_PATH", "storage")
    path = Path(base) / "inputs" / job_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _output_path(job_id: str) -> str:
    """Build output path for final MP4"""
    base = os.getenv("STORAGE_PATH", "storage")
    path = Path(base) / "outputs" / job_id / "final.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


# ─────────────────────────────────────────────
# TASK 1: GENERATE HOOKS
# ─────────────────────────────────────────────

@app.task(bind=False)
def generate_hooks_task(job: dict) -> dict:
    """
    Generate hook A/B variants for the job topic.

    Input:  job dict with job_id, brand, topic, tone
    Output: job dict enriched with hook variants saved to store
    """
    job_id = job["job_id"]
    update_job_status(job_id, "generating_hooks")

    try:
        generator = HookGenerator()
        variants = generator.generate(
            topic=job["topic"],
            brand=job["brand"],
        )

        save_hook_variants(job_id, variants)
        update_job_status(job_id, "awaiting_selection")

        logger.info(
            f"Hooks generated | job={job_id[:8]} | "
            f"variants={len(variants)} | brand={job['brand']}"
        )
        return {**job, "hook_variants": len(variants)}

    except Exception as e:
        logger.error(f"Hook generation failed | job={job_id[:8]} | error={e}")
        update_job_status(job_id, "failed", error_message=str(e))
        return {**job, "status": "failed", "error_message": str(e)}


# ─────────────────────────────────────────────
# TASK 2: SYNTHESIZE VOICE
# ─────────────────────────────────────────────

@app.task(bind=False)
def synthesize_voice_task(job: dict) -> dict:
    """
    Convert selected script to brand-voiced WAV audio.

    Input:  job dict with selected_script
    Output: job dict enriched with voice_path
    """
    job_id = job["job_id"]
    update_job_status(job_id, "processing")

    try:
        engine = VoiceEngine()

        script = job.get("selected_script", job.get("topic", ""))
        voice_path = _storage_path(job_id, "voice.wav")

        engine.synthesize(
            text=script,
            brand=job["brand"],
            output_path=voice_path
        )

        logger.info(f"Voice synthesized | job={job_id[:8]} | path={voice_path}")

        enriched = {**job, "voice_path": voice_path}
        # Chain to next task
        select_clip_task(enriched)
        return enriched

    except Exception as e:
        logger.error(f"Voice synthesis failed | job={job_id[:8]} | error={e}")
        update_job_status(job_id, "failed", error_message=str(e))
        return {**job, "status": "failed", "error_message": str(e)}


# ─────────────────────────────────────────────
# TASK 3: SELECT CLIP
# ─────────────────────────────────────────────

@app.task(bind=False)
def select_clip_task(job: dict) -> dict:
    """
    Find the best matching background clip for the script.

    Input:  job dict with selected_script, brand
    Output: job dict enriched with bg_clip_path (or None → color bg)
    """
    job_id = job["job_id"]

    try:
        selector = ClipSelector()

        script = job.get("selected_script", job.get("topic", ""))
        brand_config = _load_brand_config(job["brand"])
        target_duration = brand_config.get("video_duration_target", 25.0)

        clip = selector.select_best(
            script=script,
            brand=job["brand"],
            target_duration=float(target_duration)
        )

        logger.info(
            f"Clip selected | job={job_id[:8]} | "
            f"id={clip['id']} | score={clip['score']:.3f}"
        )

        enriched = {**job, "bg_clip_path": clip["local_path"]}

    except Exception as e:
        logger.warning(
            f"Clip selection failed | job={job_id[:8]} | "
            f"error={e} | using color background"
        )
        # Non-fatal — FFmpeg uses solid color background
        enriched = {**job, "bg_clip_path": None}

    # Always chain to compose — clip failure is recoverable
    compose_video_task(enriched)
    return enriched


# ─────────────────────────────────────────────
# TASK 4: COMPOSE VIDEO
# ─────────────────────────────────────────────

@app.task(bind=False)
def compose_video_task(job: dict) -> dict:
    """
    Assemble final MP4 from voice + clip + brand overlay.

    Input:  job dict with voice_path, bg_clip_path
    Output: job dict enriched with output_path
    """
    job_id = job["job_id"]
    update_job_status(job_id, "composing")

    try:
        composer = VideoComposer()

        brand_config = _load_brand_config(job["brand"])
        duration = float(brand_config.get("video_duration_target", 25.0))
        output_path = _output_path(job_id)

        compose_request = {
            "job_id":       job_id,
            "brand":        job["brand"],
            "voice_path":   job.get("voice_path", ""),
            "bg_clip_path": job.get("bg_clip_path"),
            "output_path":  output_path,
            "duration_sec": duration,
        }

        start_time = time.time()
        composer.compose(compose_request)
        render_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Video composed | job={job_id[:8]} | "
            f"output={output_path} | render={render_ms}ms"
        )

        enriched = {
            **job,
            "output_path":    output_path,
            "render_time_ms": render_ms,
            "duration_sec":   duration,
        }

        # Generate thumbnails in parallel with subs
        generate_thumbnails_task(enriched)
        # Chain to subtitle generation
        generate_subs_task(enriched)
        return enriched

    except Exception as e:
        logger.error(f"Video compose failed | job={job_id[:8]} | error={e}")
        update_job_status(job_id, "failed", error_message=str(e))
        return {**job, "status": "failed", "error_message": str(e)}


# ─────────────────────────────────────────────
# TASK 5: GENERATE SUBTITLES
# ─────────────────────────────────────────────

@app.task(bind=False)
def generate_subs_task(job: dict) -> dict:
    """
    Transcribe voice and generate ASS subtitle file.
    Burns subtitles into final video via re-compose if needed.

    Input:  job dict with voice_path, output_path
    Output: job dict enriched with subtitle_path, subtitle_coverage
    """
    job_id = job["job_id"]

    try:
        engine = SubtitleEngine()

        voice_path = job.get("voice_path", "")
        sub_path = _storage_path(job_id, "subtitles.ass")

        if voice_path and Path(voice_path).exists():
            segments = engine.transcribe(voice_path)
            engine.save_ass(segments, brand=job["brand"], output_path=sub_path)
            coverage = engine.calculate_coverage(
                segments,
                total_duration=job.get("duration_sec", 25.0)
            )
            logger.info(
                f"Subtitles generated | job={job_id[:8]} | "
                f"coverage={coverage:.2f} | path={sub_path}"
            )
        else:
            sub_path = None
            coverage = 0.0
            logger.warning(f"No voice file for subtitles | job={job_id[:8]}")

        enriched = {
            **job,
            "subtitle_path":     sub_path,
            "subtitle_coverage": coverage,
        }

        # Chain to QA
        qa_check_task(enriched)
        return enriched

    except Exception as e:
        logger.warning(
            f"Subtitle generation failed | job={job_id[:8]} | "
            f"error={e} | continuing to QA without subs"
        )
        # Non-fatal — QA runs without subtitle coverage
        enriched = {**job, "subtitle_path": None, "subtitle_coverage": 0.0}
        qa_check_task(enriched)
        return enriched


# ─────────────────────────────────────────────
# TASK 6: QA CHECK
# ─────────────────────────────────────────────

@app.task(bind=False)
def qa_check_task(job: dict) -> dict:
    """
    Run 7-point QA validation on the rendered video.

    Pass  → status = completed
    Fail (attempt 1) → re-run compose_video_task
    Fail (attempt 2) → status = needs_review

    Input:  job dict with output_path, duration_sec
    Output: job dict with qa_report
    """
    job_id = job["job_id"]
    update_job_status(job_id, "qa_check")

    output_path = job.get("output_path", "")
    attempt = job.get("retry_count", 0)

    try:
        validator = QAValidator()

        report = validator.validate(
            video_path=output_path,
            target_duration=float(job.get("duration_sec", 25.0)),
            subtitle_coverage=float(job.get("subtitle_coverage", 0.0)),
            avatar_present=bool(job.get("avatar_path")),
        )

        save_qa_report(job_id, report)

        if report["overall_pass"]:
            update_job_status(
                job_id, "completed",
                output_path=output_path,
                qa_passed=True,
            )
            logger.info(f"QA PASSED | job={job_id[:8]}")
            completed_job = {**job, "status": "completed"}
            # Chain to post generation + Telegram publish
            generate_post_and_publish_task(completed_job)
            return completed_job

        else:
            logger.warning(
                f"QA FAILED | job={job_id[:8]} | "
                f"attempt={attempt + 1} | "
                f"reasons={report['failure_reasons']}"
            )

            if validator.should_retry(attempt=attempt + 1):
                # Auto-retry: re-run compose
                retry_job = {**job, "retry_count": attempt + 1}
                update_job_status(job_id, "composing")
                compose_video_task(retry_job)
                return retry_job
            else:
                # Max retries reached
                update_job_status(
                    job_id, "needs_review",
                    error_message="; ".join(report["failure_reasons"]),
                    qa_passed=False,
                )
                logger.error(
                    f"QA FAILED max retries | job={job_id[:8]} → needs_review"
                )
                return {**job, "status": "needs_review"}

    except Exception as e:
        logger.error(f"QA check crashed | job={job_id[:8]} | error={e}")
        update_job_status(job_id, "failed", error_message=str(e))
        return {**job, "status": "failed", "error_message": str(e)}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _load_brand_config(brand: str) -> dict:
    """Load brand config from brands.json"""
    import json
    config_path = Path(__file__).parent.parent / "config" / "brands.json"
    with open(config_path) as f:
        brands = json.load(f)
    return brands.get(brand, {})


# ─────────────────────────────────────────────
# TASK 7: GENERATE POST + PUBLISH TO TELEGRAM
# ─────────────────────────────────────────────

@app.task(bind=False)
def generate_post_and_publish_task(job: dict) -> dict:
    """
    Generate social post bundle then publish to Telegram.

    Input:  completed job dict with output_path, selected_script
    Output: job dict enriched with post_bundle_path, telegram_message_id

    Both steps are non-fatal:
      - Post generation failure → logs warning, skips Telegram
      - Telegram failure → logs warning, job stays completed
    """
    job_id = job["job_id"]
    script = job.get("selected_script", job.get("topic", ""))

    # ── Step 1: Generate post bundle ──────────
    post_bundle = None
    post_bundle_path = None

    try:
        generator    = PostGenerator()
        post_bundle  = generator.generate(script=script, brand=job["brand"])
        bundle_path  = _storage_path(job_id, "post_bundle.json")
        post_bundle_path = generator.save_bundle(post_bundle, bundle_path)

        update_job_status(
            job_id, "completed",
            post_bundle_path=post_bundle_path,
        )

        logger.info(
            f"Post bundle generated | job={job_id[:8]} | "
            f"title={post_bundle.get('title', '')[:40]}"
        )

    except Exception as e:
        logger.warning(
            f"Post generation failed | job={job_id[:8]} | "
            f"error={e} | job remains completed"
        )

    # ── Step 2: Publish to Telegram ───────────
    if post_bundle and job.get("output_path"):
        try:
            publisher = TelegramPublisher()

            if publisher.is_configured():
                result = publisher.publish_video(
                    video_path=job["output_path"],
                    bundle=post_bundle,
                    platform="tiktok",
                )

                if not result.get("skipped"):
                    update_job_status(
                        job_id, "completed",
                        telegram_message_id=result.get("message_id"),
                        telegram_published_at=result.get("published_at"),
                    )
                    logger.info(
                        f"Published to Telegram ✓ | job={job_id[:8]} | "
                        f"message_id={result.get('message_id')}"
                    )
            else:
                logger.info(
                    f"Telegram not configured | job={job_id[:8]} | skipping"
                )

        except Exception as e:
            logger.warning(
                f"Telegram publish failed | job={job_id[:8]} | "
                f"error={e} | job remains completed"
            )

    return {
        **job,
        "post_bundle_path":    post_bundle_path,
        "post_bundle":         post_bundle,
    }


# ─────────────────────────────────────────────
# TASK: GENERATE THUMBNAILS
# ─────────────────────────────────────────────

@app.task(bind=False)
def generate_thumbnails_task(job: dict) -> dict:
    """
    Generate 3 branded thumbnail variants for the rendered video.

    Input:  job dict with output_path, post_bundle or topic
    Output: job dict enriched with thumbnail_paths list

    Non-fatal — thumbnail failure does not block job completion.
    """
    job_id    = job["job_id"]
    out_path  = job.get("output_path", "")
    post_bundle = job.get("post_bundle") or {
        "title":    job.get("topic", ""),
        "caption":  "",
        "hashtags": [],
        "cta_link": "",
    }

    if not out_path or not Path(out_path).exists():
        logger.warning(f"No output file for thumbnails | job={job_id[:8]}")
        return job

    try:
        engine     = ThumbnailEngine()
        output_dir = str(Path(out_path).parent)

        thumbnails = engine.generate(
            video_path=out_path,
            bundle=post_bundle,
            brand=job["brand"],
            output_dir=output_dir,
        )

        thumbnail_paths = [t["path"] for t in thumbnails]

        update_job_status(
            job_id, _jobs.get(job_id, {}).get("status", "completed"),
            thumbnail_paths=thumbnail_paths,
        )

        logger.info(
            f"Thumbnails generated | job={job_id[:8]} | "
            f"count={len(thumbnails)}"
        )

        return {**job, "thumbnail_paths": thumbnail_paths, "thumbnails": thumbnails}

    except Exception as e:
        logger.warning(
            f"Thumbnail generation failed | job={job_id[:8]} | "
            f"error={e} | job continues"
        )
        return job


# ─────────────────────────────────────────────
# TASK: NIGHTLY STORAGE SWEEP
# ─────────────────────────────────────────────

@app.task(bind=False)
def nightly_storage_sweep_task() -> dict:
    """
    Nightly Celery beat task — archives old files to B2, deletes expired.
    Runs at 02:00 UTC daily.

    Returns summary dict with archived, deleted, errors counts.
    """
    logger.info("Nightly storage sweep starting...")

    lifecycle = StorageLifecycle()

    # Get all completed jobs from store
    jobs = [
        j for j in _jobs.values()
        if j.get("status") == "completed"
        and j.get("output_storage_tier") not in ("deleted",)
    ]

    summary = lifecycle.run_nightly_sweep(jobs)

    # Update storage tiers in job store
    for job in jobs:
        if lifecycle.should_archive(job):
            _jobs[job["job_id"]]["output_storage_tier"] = "archived"
        elif lifecycle.should_delete(job):
            _jobs[job["job_id"]]["output_storage_tier"] = "deleted"
            _jobs[job["job_id"]]["output_url"] = None

    logger.info(f"Nightly sweep complete | {summary}")
    return summary


# ─────────────────────────────────────────────
# TASK: NIGHTLY DATABASE BACKUP
# ─────────────────────────────────────────────

@app.task(bind=False)
def nightly_db_backup_task() -> dict:
    """
    Nightly Celery beat task — pg_dump → B2 → purge old.
    Runs at 03:00 UTC daily alongside storage sweep.

    Returns summary dict with success, b2_path, deleted_count.
    """
    logger.info("Nightly DB backup starting...")
    try:
        from database.backup_manager import BackupManager
        manager = BackupManager()
        summary = manager.run_backup_cycle()
        logger.info(f"Nightly backup complete | {summary}")
        return summary
    except Exception as e:
        logger.error(f"Nightly backup failed: {e}")
        return {"success": False, "error": str(e)}
