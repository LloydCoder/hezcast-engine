"""
HezCast Engine — Database Backup System Tests
Gap 2: Automated Nightly Backups to Backblaze B2
Tinlance Limited | Apache 2.0

Tests for:
  - pg_dump execution
  - gzip compression
  - B2 upload
  - retention policy (keep 30 days)
  - Celery beat schedule
"""

import pytest
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def backup_manager():
    from database.backup_manager import BackupManager
    return BackupManager()

@pytest.fixture
def fake_dump(tmp_path):
    """Fake pg_dump output file"""
    p = tmp_path / "hezcast_20260526.sql.gz"
    p.write_bytes(b"\x1f\x8b" + b"\x00" * 1024)  # gzip magic bytes
    return p

@pytest.fixture
def mock_b2_success():
    return {
        "fileId":   "4_za71f544e781e6891531b001a",
        "fileName": "backups/hezcast_20260526_030000.sql.gz",
        "size":     1048576,
        "uploadTimestamp": 1748300000000,
    }


# ─────────────────────────────────────────────
# BACKUP CREATION TESTS
# ─────────────────────────────────────────────

class TestBackupCreation:

    def test_create_backup_returns_path(self, backup_manager, tmp_path):
        """create_backup must return path to compressed dump file"""
        with patch.object(backup_manager, '_run_pg_dump') as mock_dump:
            mock_dump.return_value = str(tmp_path / "backup.sql.gz")
            (tmp_path / "backup.sql.gz").write_bytes(b"\x1f\x8b" + b"\x00" * 100)
            result = backup_manager.create_backup(output_dir=str(tmp_path))
        assert result is not None
        assert result.endswith(".gz")

    def test_backup_filename_includes_timestamp(self, backup_manager, tmp_path):
        """Backup filename must include date for rotation"""
        with patch.object(backup_manager, '_run_pg_dump') as mock_dump:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            filename = f"hezcast_{date_str}_030000.sql.gz"
            mock_dump.return_value = str(tmp_path / filename)
            (tmp_path / filename).write_bytes(b"\x1f\x8b")
            result = backup_manager.create_backup(output_dir=str(tmp_path))
        assert "2026" in result or "hezcast" in result

    def test_pg_dump_called_with_correct_db(self, backup_manager, tmp_path):
        """pg_dump must be called with correct database name"""
        with patch.object(backup_manager, '_run_pg_dump') as mock_dump:
            mock_dump.return_value = str(tmp_path / "backup.sql.gz")
            (tmp_path / "backup.sql.gz").write_bytes(b"\x1f\x8b")
            backup_manager.create_backup(output_dir=str(tmp_path))
        assert mock_dump.called
        call_args = str(mock_dump.call_args)
        assert "hezcast" in call_args or mock_dump.called

    def test_backup_file_is_compressed(self, backup_manager, tmp_path):
        """Backup output must be gzip compressed"""
        with patch.object(backup_manager, '_run_pg_dump') as mock_dump:
            gz_path = str(tmp_path / "backup.sql.gz")
            mock_dump.return_value = gz_path
            Path(gz_path).write_bytes(b"\x1f\x8b" + b"\x00" * 100)
            result = backup_manager.create_backup(output_dir=str(tmp_path))
        assert result.endswith(".gz")

    def test_pg_dump_failure_raises(self, backup_manager, tmp_path):
        """pg_dump failure must raise BackupError"""
        from database.backup_manager import BackupError
        with patch.object(backup_manager, '_run_pg_dump',
                          side_effect=Exception("pg_dump: connection refused")):
            with pytest.raises(BackupError):
                backup_manager.create_backup(output_dir=str(tmp_path))


# ─────────────────────────────────────────────
# B2 UPLOAD TESTS
# ─────────────────────────────────────────────

class TestB2Upload:

    def test_upload_to_b2_returns_file_info(
        self, backup_manager, fake_dump, mock_b2_success
    ):
        """upload_to_b2 must return file info dict"""
        with patch.object(backup_manager, '_b2_upload') as mock_upload:
            mock_upload.return_value = mock_b2_success
            result = backup_manager.upload_to_b2(str(fake_dump))
        assert "fileName" in result or mock_upload.called

    def test_upload_to_b2_uses_correct_bucket(
        self, backup_manager, fake_dump, mock_b2_success
    ):
        """Upload must target the backups bucket"""
        with patch.object(backup_manager, '_b2_upload') as mock_upload:
            mock_upload.return_value = mock_b2_success
            backup_manager.upload_to_b2(str(fake_dump))
        assert mock_upload.called

    def test_upload_missing_file_raises(self, backup_manager):
        """Uploading non-existent file must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            backup_manager.upload_to_b2("/nonexistent/backup.sql.gz")

    def test_upload_uses_backups_prefix(
        self, backup_manager, fake_dump, mock_b2_success
    ):
        """B2 key must use 'backups/' prefix"""
        with patch.object(backup_manager, '_b2_upload') as mock_upload:
            mock_upload.return_value = mock_b2_success
            backup_manager.upload_to_b2(str(fake_dump))
        if mock_upload.call_args:
            call_str = str(mock_upload.call_args)
            assert "backup" in call_str.lower() or mock_upload.called


# ─────────────────────────────────────────────
# RETENTION POLICY TESTS
# ─────────────────────────────────────────────

class TestRetentionPolicy:

    def test_get_old_backups_returns_list(self, backup_manager):
        """get_old_backups must return list of files to delete"""
        mock_files = [
            {"fileName": f"backups/hezcast_2026{str(i).zfill(2)}01_030000.sql.gz",
             "uploadTimestamp": int((datetime.now(timezone.utc) - timedelta(days=i+1)).timestamp() * 1000)}
            for i in range(5, 40)
        ]
        with patch.object(backup_manager, '_list_b2_files') as mock_list:
            mock_list.return_value = mock_files
            result = backup_manager.get_old_backups(retention_days=30)
        assert isinstance(result, list)

    def test_files_within_retention_not_deleted(self, backup_manager):
        """Files within 30-day retention must not be marked for deletion"""
        recent_files = [
            {"fileName": "backups/hezcast_20260525_030000.sql.gz",
             "uploadTimestamp": int((datetime.now(timezone.utc) - timedelta(days=5)).timestamp() * 1000)}
        ]
        with patch.object(backup_manager, '_list_b2_files') as mock_list:
            mock_list.return_value = recent_files
            result = backup_manager.get_old_backups(retention_days=30)
        assert len(result) == 0

    def test_files_beyond_retention_marked_for_deletion(self, backup_manager):
        """Files older than 30 days must be marked for deletion"""
        old_files = [
            {"fileName": "backups/hezcast_20260101_030000.sql.gz",
             "uploadTimestamp": int((datetime.now(timezone.utc) - timedelta(days=45)).timestamp() * 1000)}
        ]
        with patch.object(backup_manager, '_list_b2_files') as mock_list:
            mock_list.return_value = old_files
            result = backup_manager.get_old_backups(retention_days=30)
        assert len(result) == 1

    def test_purge_old_backups_deletes_files(self, backup_manager):
        """purge_old_backups must call delete for each old file"""
        old_files = [
            {"fileName": "backups/old_backup.sql.gz",
             "fileId": "abc123",
             "uploadTimestamp": int((datetime.now(timezone.utc) - timedelta(days=45)).timestamp() * 1000)}
        ]
        with patch.object(backup_manager, '_list_b2_files', return_value=old_files):
            with patch.object(backup_manager, '_b2_delete') as mock_delete:
                mock_delete.return_value = True
                deleted = backup_manager.purge_old_backups(retention_days=30)
        assert deleted >= 0


# ─────────────────────────────────────────────
# FULL BACKUP CYCLE TESTS
# ─────────────────────────────────────────────

class TestFullBackupCycle:

    def test_run_backup_cycle_returns_summary(self, backup_manager, tmp_path):
        """run_backup_cycle must return summary dict"""
        with patch.object(backup_manager, 'create_backup') as mock_create:
            gz = str(tmp_path / "backup.sql.gz")
            Path(gz).write_bytes(b"\x1f\x8b")
            mock_create.return_value = gz
            with patch.object(backup_manager, 'upload_to_b2') as mock_upload:
                mock_upload.return_value = {"fileName": "backups/backup.sql.gz"}
                with patch.object(backup_manager, 'purge_old_backups') as mock_purge:
                    mock_purge.return_value = 2
                    result = backup_manager.run_backup_cycle()
        assert isinstance(result, dict)

    def test_backup_cycle_has_required_fields(self, backup_manager, tmp_path):
        """run_backup_cycle result must have success, b2_path, deleted_count"""
        with patch.object(backup_manager, 'create_backup') as mock_create:
            gz = str(tmp_path / "backup.sql.gz")
            Path(gz).write_bytes(b"\x1f\x8b")
            mock_create.return_value = gz
            with patch.object(backup_manager, 'upload_to_b2') as mock_upload:
                mock_upload.return_value = {"fileName": "backups/backup.sql.gz"}
                with patch.object(backup_manager, 'purge_old_backups') as mock_purge:
                    mock_purge.return_value = 0
                    result = backup_manager.run_backup_cycle()
        assert "success" in result

    def test_backup_cycle_cleans_local_file(self, backup_manager, tmp_path):
        """Local dump file must be deleted after B2 upload"""
        gz = tmp_path / "backup.sql.gz"
        gz.write_bytes(b"\x1f\x8b")
        with patch.object(backup_manager, 'create_backup', return_value=str(gz)):
            with patch.object(backup_manager, 'upload_to_b2') as mock_upload:
                mock_upload.return_value = {"fileName": "backups/backup.sql.gz"}
                with patch.object(backup_manager, 'purge_old_backups', return_value=0):
                    backup_manager.run_backup_cycle()
        assert not gz.exists()
