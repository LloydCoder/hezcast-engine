"""
HezCast Engine — Database Backup Manager
Gap 2: Automated Nightly Backups to Backblaze B2
Tinlance Limited | Apache 2.0

Backup pipeline:
  1. pg_dump → compressed .sql.gz file
  2. Upload to Backblaze B2 under backups/ prefix
  3. Delete local file after upload
  4. Purge B2 files older than 30 days
  5. Log summary

Schedule: Celery beat at 03:00 UTC nightly

Setup:
  1. Add B2_KEY_ID + B2_APP_KEY to .env (already there from Phase 6)
  2. Create bucket: hezcast-backups (separate from video bucket)
  3. Celery beat picks it up automatically

Cost estimate:
  ~500KB per backup × 30 days = ~15MB/month = $0.001/month
"""

import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# B2 bucket for backups (separate from video storage)
BACKUP_BUCKET  = os.getenv("B2_BACKUP_BUCKET", "hezcast-backups")
BACKUP_PREFIX  = "backups"
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))


class BackupManager:
    """
    Manages nightly database backups for HezCast.

    Usage:
        manager = BackupManager()

        # Run full backup cycle (dump → upload → purge → clean)
        result = manager.run_backup_cycle()

        # Or individual steps
        gz_path = manager.create_backup(output_dir="/tmp")
        info    = manager.upload_to_b2(gz_path)
        deleted = manager.purge_old_backups(retention_days=30)
    """

    def __init__(self):
        self._b2_client = None

    # ─────────────────────────────────────────
    # FULL BACKUP CYCLE
    # ─────────────────────────────────────────

    def run_backup_cycle(
        self,
        output_dir: str = "/tmp/hezcast_backups",
        retention_days: int = RETENTION_DAYS,
    ) -> dict:
        """
        Full nightly backup cycle:
          1. Create compressed pg_dump
          2. Upload to B2
          3. Delete local file
          4. Purge old B2 files

        Returns:
            dict with success, b2_path, size_bytes, deleted_count, duration_sec
        """
        import time
        start = time.time()

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        summary = {
            "success":       False,
            "b2_path":       None,
            "size_bytes":    0,
            "deleted_count": 0,
            "error":         None,
        }

        local_path = None

        try:
            # Step 1: Create backup
            logger.info("Starting backup cycle...")
            local_path = self.create_backup(output_dir=output_dir)
            summary["size_bytes"] = Path(local_path).stat().st_size
            logger.info(f"Dump created: {local_path} ({summary['size_bytes']:,} bytes)")

            # Step 2: Upload to B2
            info = self.upload_to_b2(local_path)
            summary["b2_path"] = info.get("fileName", "")
            logger.info(f"Uploaded to B2: {summary['b2_path']}")

            # Step 3: Delete local file
            Path(local_path).unlink(missing_ok=True)
            local_path = None
            logger.info("Local dump file deleted")

            # Step 4: Purge old backups
            deleted = self.purge_old_backups(retention_days=retention_days)
            summary["deleted_count"] = deleted
            if deleted > 0:
                logger.info(f"Purged {deleted} old backup(s)")

            summary["success"] = True
            summary["duration_sec"] = round(time.time() - start, 2)

            logger.info(
                f"Backup cycle complete ✓ | "
                f"size={summary['size_bytes']:,}B | "
                f"deleted={deleted} | "
                f"duration={summary['duration_sec']}s"
            )

        except Exception as e:
            summary["error"] = str(e)
            logger.error(f"Backup cycle failed: {e}")
            # Clean up local file if upload failed
            if local_path and Path(local_path).exists():
                Path(local_path).unlink(missing_ok=True)

        return summary

    # ─────────────────────────────────────────
    # BACKUP CREATION
    # ─────────────────────────────────────────

    def create_backup(self, output_dir: str = "/tmp") -> str:
        """
        Create a compressed pg_dump of the HezCast database.

        Args:
            output_dir: Directory to write the dump file

        Returns:
            Path to the .sql.gz file

        Raises:
            BackupError: If pg_dump fails
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename  = f"hezcast_{timestamp}.sql.gz"
        out_path  = str(Path(output_dir) / filename)

        try:
            result = self._run_pg_dump(out_path)
            logger.info(f"pg_dump completed: {out_path}")
            return result
        except Exception as e:
            raise BackupError(f"pg_dump failed: {e}")

    # ─────────────────────────────────────────
    # B2 OPERATIONS
    # ─────────────────────────────────────────

    def upload_to_b2(self, local_path: str) -> dict:
        """
        Upload backup file to Backblaze B2.

        Args:
            local_path: Path to the .sql.gz file

        Returns:
            dict with fileName, fileId, size

        Raises:
            FileNotFoundError: If local file doesn't exist
        """
        if not Path(local_path).exists():
            raise FileNotFoundError(f"Backup file not found: {local_path}")

        filename = Path(local_path).name
        b2_key   = f"{BACKUP_PREFIX}/{filename}"

        logger.info(f"Uploading to B2: {b2_key}")
        result = self._b2_upload(local_path, b2_key)
        return result

    def get_old_backups(self, retention_days: int = RETENTION_DAYS) -> list:
        """
        Get list of B2 backup files older than retention_days.

        Args:
            retention_days: Files older than this are candidates for deletion

        Returns:
            List of file dicts past the retention window
        """
        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=retention_days)).timestamp()
            * 1000
        )

        all_files = self._list_b2_files()
        old_files = [
            f for f in all_files
            if f.get("uploadTimestamp", 0) < cutoff_ms
        ]

        return old_files

    def purge_old_backups(self, retention_days: int = RETENTION_DAYS) -> int:
        """
        Delete B2 backup files older than retention_days.

        Args:
            retention_days: Keep files newer than this many days

        Returns:
            Number of files deleted
        """
        old_files = self.get_old_backups(retention_days)

        deleted = 0
        for file_info in old_files:
            try:
                self._b2_delete(
                    file_id=file_info.get("fileId", ""),
                    file_name=file_info.get("fileName", ""),
                )
                deleted += 1
                logger.info(f"Deleted old backup: {file_info.get('fileName')}")
            except Exception as e:
                logger.warning(f"Could not delete {file_info.get('fileName')}: {e}")

        return deleted

    # ─────────────────────────────────────────
    # INTERNAL OPERATIONS (mockable in tests)
    # ─────────────────────────────────────────

    def _run_pg_dump(self, output_path: str) -> str:
        """
        Execute pg_dump and compress output to .sql.gz.
        In tests: mocked via patch.object(manager, '_run_pg_dump').
        """
        db_url = os.getenv("DATABASE_URL", "")

        if not db_url:
            # Build from parts
            host     = os.getenv("DB_HOST",     "localhost")
            port     = os.getenv("DB_PORT",     "5432")
            database = os.getenv("DB_NAME",     "hezcast")
            user     = os.getenv("DB_USER",     "hezcast_app")
            password = os.getenv("DB_PASSWORD", "")

            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password

            cmd = [
                "pg_dump",
                "--format=custom",
                "--no-password",
                f"--host={host}",
                f"--port={port}",
                f"--username={user}",
                database,
            ]
        else:
            env = os.environ.copy()
            cmd = ["pg_dump", "--format=custom", "--no-password", db_url]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with gzip.open(output_path, "wb") as gz_file:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, timeout=300
            )
            if proc.returncode != 0:
                raise BackupError(
                    f"pg_dump exited {proc.returncode}: "
                    f"{proc.stderr.decode()[:500]}"
                )
            gz_file.write(proc.stdout)

        return output_path

    def _b2_upload(self, local_path: str, b2_key: str) -> dict:
        """Upload file to B2. In tests: mocked."""
        import boto3
        from botocore.config import Config

        client = self._get_b2_client()
        endpoint = os.getenv("B2_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")

        with open(local_path, "rb") as f:
            client.upload_fileobj(
                f, BACKUP_BUCKET, b2_key,
                ExtraArgs={"ContentType": "application/gzip"}
            )

        return {
            "fileName": b2_key,
            "bucket":   BACKUP_BUCKET,
            "size":     Path(local_path).stat().st_size,
        }

    def _b2_delete(self, file_id: str, file_name: str) -> bool:
        """Delete file from B2. In tests: mocked."""
        try:
            client = self._get_b2_client()
            client.delete_object(Bucket=BACKUP_BUCKET, Key=file_name)
            return True
        except Exception as e:
            logger.error(f"B2 delete failed: {e}")
            return False

    def _list_b2_files(self) -> list:
        """List backup files in B2. In tests: mocked."""
        try:
            client = self._get_b2_client()
            response = client.list_objects_v2(
                Bucket=BACKUP_BUCKET,
                Prefix=f"{BACKUP_PREFIX}/",
            )
            files = []
            for obj in response.get("Contents", []):
                files.append({
                    "fileName":        obj["Key"],
                    "fileId":          obj.get("ETag", ""),
                    "uploadTimestamp": int(obj["LastModified"].timestamp() * 1000),
                    "size":            obj["Size"],
                })
            return files
        except Exception as e:
            logger.warning(f"Could not list B2 files: {e}")
            return []

    def _get_b2_client(self):
        """Lazy-init B2 S3-compatible client"""
        if self._b2_client is None:
            import boto3
            from botocore.config import Config
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


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class BackupError(Exception):
    """Raised when database backup fails"""
    pass
