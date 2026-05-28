"""
HezCast Engine — Celery Configuration
Tinlance Limited | Apache 2.0
"""

import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "hezcast",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["workers.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Queue routing
    task_routes={
        "workers.tasks.generate_hooks_task":   {"queue": "script"},
        "workers.tasks.synthesize_voice_task": {"queue": "voice"},
        "workers.tasks.select_clip_task":      {"queue": "default"},
        "workers.tasks.compose_video_task":    {"queue": "compose"},
        "workers.tasks.generate_subs_task":    {"queue": "compose"},
        "workers.tasks.qa_check_task":         {"queue": "default"},
    },

    # Retry settings
    task_max_retries=3,
    task_default_retry_delay=30,

    # Nightly scheduled tasks (Celery beat)
    beat_schedule={
        "nightly-db-backup": {
            "task":     "workers.tasks.nightly_db_backup_task",
            "schedule": 86400,
            "options":  {"queue": "default"},
        },
        "nightly-storage-sweep": {
            "task":     "workers.tasks.nightly_storage_sweep_task",
            "schedule": 86400,
            "options":  {"queue": "default"},
        },
    },
)
