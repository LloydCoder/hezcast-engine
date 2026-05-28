"""
HezCast Engine — Storage Lifecycle Manager
Tinlance Limited | Apache 2.0

Nightly Celery beat task that manages video file retention:

  Day 0–7:    File lives on local VPS disk (hot storage)
  Day 7+:     Upload to Backblaze B2, delete local (warm storage)
  Day 30/90/180: Delete from B2 based on plan retention window

Retention policy per plan:
  free:    1 day local  | 0 days B2 (deleted immediately after)
  starter: 7 days local | 30 days B2
  pro:     7 days local | 90 days B2
  agency:  7 days local | 180 days B2

Keeps VPS disk lean. Uses Backblaze B2 (already in Tinlance stack).
Creates upgrade pressure — free users see 24h deletion countdown.
"""

import logging
import os
import boto3
from botocore.config import Config
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# RETENTION POLICY
# ─────────────────────────────────────────────

RETENTION_POLICY = {
    "free":    {"local_days": 1,  "archive_days": 0},
    "starter": {"local_days": 7,  "archive_days": 30},
    "pro":     {"local_days": 7,  "archive_days": 90},
    "agency":  {"local_days": 7,  "archive_days": 180},
}

DEFAULT_PLAN = "free"


class StorageLifecycle:
    """
    Manages the full lifecycle of HezCast output files:
      local disk → Backblaze B2 archive → deletion

    Usage:
        lifecycle = StorageLifecycle()

        # Process a single job
        if lifecycle.should_archive(job):
            b2_url = lifecycle.archive_to_b2(job)

        if lifecycle.should_delete(job):
            lifecycle.delete_from_b2(job)

        # Or run the full nightly sweep (called by Celery beat)
        lifecycle.run_nightly_sweep(jobs)
    """

    B2_BUCKET = os.getenv("B2_BUCKET_NAME", "hezcast-outputs")
    B2_PREFIX = "videos"

    def __init__(self):
        self._b2_client = None

    # ─────────────────────────────────────────
    # RETENTION GETTERS
    # ─────────────────────────────────────────

    def get_local_retention_days(self, plan: str) -> int:
        """Days a file stays on local VPS disk before archiving"""
        policy = RETENTION_POLICY.get(plan, RETENTION_POLICY[DEFAULT_PLAN])
        return policy["local_days"]

    def get_archive_retention_days(self, plan: str) -> int:
        """Days a file stays in B2 archive before permanent deletion"""
        policy = RETENTION_POLICY.get(plan, RETENTION_POLICY[DEFAULT_PLAN])
        return policy["archive_days"]

    # ─────────────────────────────────────────
    # LIFECYCLE DECISIONS
    # ─────────────────────────────────────────

    def should_archive(self, job: dict) -> bool:
        """
        Returns True if the job's local file should be archived to B2.

        Conditions:
        - output_storage_tier is 'local'
        - output_path exists and is not None
        - age_days >= local_retention_days for the plan
        """
        if job.get("output_storage_tier") != "local":
            return False

        if not job.get("output_path"):
            return False

        plan = job.get("plan", DEFAULT_PLAN)
        age = self.get_age_days(job.get("completed_at"))
        retention = self.get_local_retention_days(plan)

        return age >= retention

    def should_delete(self, job: dict) -> bool:
        """
        Returns True if the job's file should be permanently deleted.

        For free plan: delete local after 1 day (no B2 archive)
        For paid plans: delete from B2 after archive_retention_days
        """
        tier = job.get("output_storage_tier", "")

        if tier == "deleted":
            return False

        plan = job.get("plan", DEFAULT_PLAN)
        age = self.get_age_days(job.get("completed_at"))
        local_days = self.get_local_retention_days(plan)
        archive_days = self.get_archive_retention_days(plan)

        # Free plan: delete local after 1 day
        if plan == "free":
            return tier == "local" and age >= local_days

        # Paid plans: delete from B2 after total retention window
        total_days = local_days + archive_days
        return age >= total_days

    # ─────────────────────────────────────────
    # ARCHIVE OPERATION
    # ─────────────────────────────────────────

    def archive_to_b2(self, job: dict) -> str:
        """
        Upload local video file to Backblaze B2 and delete local copy.

        Args:
            job: Job dict with output_path, job_id

        Returns:
            B2 URL (str)

        Raises:
            FileNotFoundError: If local file doesn't exist
            StorageError: If B2 upload fails
        """
        local_path = job.get("output_path")
        if not local_path or not Path(local_path).exists():
            raise FileNotFoundError(
                f"Local file not found for job {job.get('job_id')}: {local_path}"
            )

        job_id = job["job_id"]
        filename = Path(local_path).name
        b2_key = f"{self.B2_PREFIX}/{job_id}/{filename}"

        logger.info(f"Archiving to B2 | job={job_id[:8]} | key={b2_key}")

        b2_url = self._upload_to_b2(local_path, b2_key)

        # Delete local file after successful upload
        Path(local_path).unlink(missing_ok=True)
        logger.info(f"Local file deleted after B2 archive | {local_path}")

        return b2_url

    def delete_from_b2(self, job: dict) -> bool:
        """
        Permanently delete file from Backblaze B2.

        Args:
            job: Job dict with job_id and output_url

        Returns:
            True on success
        """
        job_id = job.get("job_id", "unknown")
        output_url = job.get("output_url", "")

        if not output_url:
            logger.warning(f"No B2 URL to delete | job={job_id[:8]}")
            return False

        # Extract B2 key from URL
        b2_key = self._url_to_b2_key(output_url)

        logger.info(f"Deleting from B2 | job={job_id[:8]} | key={b2_key}")
        return self._delete_from_b2(b2_key)

    def delete_local(self, job: dict) -> None:
        """
        Delete local file for a job. Silent if already missing.

        Args:
            job: Job dict with output_path
        """
        local_path = job.get("output_path")
        if local_path:
            try:
                Path(local_path).unlink(missing_ok=True)
                logger.debug(f"Deleted local file: {local_path}")
            except Exception as e:
                logger.warning(f"Could not delete local file {local_path}: {e}")

    # ─────────────────────────────────────────
    # NIGHTLY SWEEP
    # ─────────────────────────────────────────

    def run_nightly_sweep(self, jobs: list[dict]) -> dict:
        """
        Process all jobs for archiving and deletion.
        Called by Celery beat at 02:00 UTC nightly.

        Returns:
            Summary dict with archived, deleted, errors counts
        """
        summary = {"archived": 0, "deleted": 0, "errors": 0, "skipped": 0}

        for job in jobs:
            try:
                if self.should_archive(job):
                    b2_url = self.archive_to_b2(job)
                    summary["archived"] += 1
                    logger.info(
                        f"Archived | job={job['job_id'][:8]} | url={b2_url[:50]}"
                    )

                elif self.should_delete(job):
                    if job.get("output_storage_tier") == "archived":
                        self.delete_from_b2(job)
                    else:
                        self.delete_local(job)
                    summary["deleted"] += 1
                    logger.info(f"Deleted | job={job['job_id'][:8]}")

                else:
                    summary["skipped"] += 1

            except Exception as e:
                summary["errors"] += 1
                logger.error(
                    f"Lifecycle error | job={job.get('job_id', 'unknown')[:8]} | {e}"
                )

        logger.info(
            f"Nightly sweep complete | "
            f"archived={summary['archived']} | "
            f"deleted={summary['deleted']} | "
            f"errors={summary['errors']} | "
            f"skipped={summary['skipped']}"
        )
        return summary

    # ─────────────────────────────────────────
    # AGE CALCULATION
    # ─────────────────────────────────────────

    def get_age_days(self, completed_at: Optional[str]) -> float:
        """
        Calculate age of a job in days from completed_at timestamp.

        Args:
            completed_at: ISO 8601 timestamp string or None

        Returns:
            Age in days (float). Returns 0.0 if completed_at is None.
        """
        if not completed_at:
            return 0.0

        try:
            dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
            return max(0.0, age)
        except Exception as e:
            logger.warning(f"Could not parse completed_at '{completed_at}': {e}")
            return 0.0

    # ─────────────────────────────────────────
    # B2 OPERATIONS (mockable in tests)
    # ─────────────────────────────────────────

    def _upload_to_b2(self, local_path: str, b2_key: str) -> str:
        """
        Upload file to Backblaze B2 using S3-compatible API.
        In tests: mocked via patch.
        """
        client = self._get_b2_client()

        with open(local_path, "rb") as f:
            client.upload_fileobj(
                f,
                self.B2_BUCKET,
                b2_key,
                ExtraArgs={"ContentType": "video/mp4"}
            )

        endpoint = os.getenv("B2_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")
        return f"{endpoint}/{self.B2_BUCKET}/{b2_key}"

    def _delete_from_b2(self, b2_key: str) -> bool:
        """Delete object from B2. In tests: mocked."""
        try:
            client = self._get_b2_client()
            client.delete_object(Bucket=self.B2_BUCKET, Key=b2_key)
            return True
        except Exception as e:
            logger.error(f"B2 delete failed for {b2_key}: {e}")
            return False

    def _get_b2_client(self):
        """Lazy-init Backblaze B2 client (S3-compatible)"""
        if self._b2_client is None:
            self._b2_client = boto3.client(
                "s3",
                endpoint_url=os.getenv(
                    "B2_ENDPOINT",
                    "https://s3.us-west-004.backblazeb2.com"
                ),
                aws_access_key_id=os.getenv("B2_KEY_ID"),
                aws_secret_access_key=os.getenv("B2_APP_KEY"),
                config=Config(signature_version="s3v4"),
            )
        return self._b2_client

    def _url_to_b2_key(self, url: str) -> str:
        """Extract B2 object key from full URL"""
        endpoint = os.getenv("B2_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")
        prefix = f"{endpoint}/{self.B2_BUCKET}/"
        if url.startswith(prefix):
            return url[len(prefix):]
        return url.split("/", 3)[-1] if "/" in url else url


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class StorageError(Exception):
    """Raised when B2 storage operations fail"""
    pass
