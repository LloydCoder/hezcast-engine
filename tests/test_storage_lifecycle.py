"""
HezCast Engine — Storage Lifecycle Manager Tests
TDD Phase 6 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

Nightly Celery beat task:
  Day 0–7:   File on local VPS disk
  Day 7+:    Archive to Backblaze B2, delete local
  Day 30/90/180: Delete from B2 based on plan retention
"""

import pytest
import os
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def lifecycle():
    from core.storage_lifecycle import StorageLifecycle
    return StorageLifecycle()

@pytest.fixture
def sample_job_local(tmp_path):
    """Job with local file, 1 day old"""
    mp4 = tmp_path / "final.mp4"
    mp4.write_bytes(b"\x00" * (10 * 1024 * 1024))
    return {
        "job_id":              "job-local-001",
        "tenant_id":           "tenant-001",
        "plan":                "starter",
        "output_path":         str(mp4),
        "output_storage_tier": "local",
        "completed_at":        (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }

@pytest.fixture
def sample_job_old_local(tmp_path):
    """Job with local file, 8 days old — should archive"""
    mp4 = tmp_path / "final.mp4"
    mp4.write_bytes(b"\x00" * (10 * 1024 * 1024))
    return {
        "job_id":              "job-old-001",
        "tenant_id":           "tenant-001",
        "plan":                "starter",
        "output_path":         str(mp4),
        "output_storage_tier": "local",
        "completed_at":        (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
    }

@pytest.fixture
def sample_job_archived():
    """Job already archived to B2, 35 days old"""
    return {
        "job_id":              "job-arch-001",
        "tenant_id":           "tenant-001",
        "plan":                "starter",
        "output_path":         None,
        "output_url":          "https://b2.backblaze.com/hezcast/job-arch-001/final.mp4",
        "output_storage_tier": "archived",
        "completed_at":        (datetime.now(timezone.utc) - timedelta(days=35)).isoformat(),
    }


# ─────────────────────────────────────────────
# RETENTION POLICY TESTS
# ─────────────────────────────────────────────

class TestRetentionPolicy:

    def test_free_local_retention_is_1_day(self, lifecycle):
        """Free plan: 1 day local retention"""
        assert lifecycle.get_local_retention_days("free") == 1

    def test_starter_local_retention_is_7_days(self, lifecycle):
        """Starter plan: 7 days local retention"""
        assert lifecycle.get_local_retention_days("starter") == 7

    def test_pro_local_retention_is_7_days(self, lifecycle):
        """Pro plan: 7 days local retention"""
        assert lifecycle.get_local_retention_days("pro") == 7

    def test_agency_local_retention_is_7_days(self, lifecycle):
        """Agency plan: 7 days local retention"""
        assert lifecycle.get_local_retention_days("agency") == 7

    def test_free_archive_retention_is_0_days(self, lifecycle):
        """Free plan: no B2 archive"""
        assert lifecycle.get_archive_retention_days("free") == 0

    def test_starter_archive_retention_is_30_days(self, lifecycle):
        """Starter plan: 30 days B2 archive"""
        assert lifecycle.get_archive_retention_days("starter") == 30

    def test_pro_archive_retention_is_90_days(self, lifecycle):
        """Pro plan: 90 days B2 archive"""
        assert lifecycle.get_archive_retention_days("pro") == 90

    def test_agency_archive_retention_is_180_days(self, lifecycle):
        """Agency plan: 180 days B2 archive"""
        assert lifecycle.get_archive_retention_days("agency") == 180

    def test_unknown_plan_defaults_to_free(self, lifecycle):
        """Unknown plan defaults to free retention"""
        assert lifecycle.get_local_retention_days("unknown") == 1
        assert lifecycle.get_archive_retention_days("unknown") == 0


# ─────────────────────────────────────────────
# SHOULD ARCHIVE TESTS
# ─────────────────────────────────────────────

class TestShouldArchive:

    def test_should_archive_when_past_local_retention(self, lifecycle, sample_job_old_local):
        """8-day-old starter job should be archived"""
        assert lifecycle.should_archive(sample_job_old_local) is True

    def test_should_not_archive_when_within_retention(self, lifecycle, sample_job_local):
        """1-day-old job should NOT be archived yet"""
        assert lifecycle.should_archive(sample_job_local) is False

    def test_should_not_archive_already_archived(self, lifecycle, sample_job_archived):
        """Already archived job should not archive again"""
        assert lifecycle.should_archive(sample_job_archived) is False

    def test_free_plan_archives_after_1_day(self, lifecycle, tmp_path):
        """Free plan job older than 1 day should archive"""
        mp4 = tmp_path / "final.mp4"
        mp4.write_bytes(b"\x00" * 1024)
        job = {
            "job_id": "free-job",
            "plan": "free",
            "output_path": str(mp4),
            "output_storage_tier": "local",
            "completed_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        }
        assert lifecycle.should_archive(job) is True

    def test_should_not_archive_when_no_output_path(self, lifecycle):
        """Job with no output_path cannot be archived"""
        job = {
            "job_id": "no-file",
            "plan": "starter",
            "output_path": None,
            "output_storage_tier": "local",
            "completed_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        }
        assert lifecycle.should_archive(job) is False


# ─────────────────────────────────────────────
# SHOULD DELETE TESTS
# ─────────────────────────────────────────────

class TestShouldDelete:

    def test_should_delete_free_after_1_day(self, lifecycle, tmp_path):
        """Free plan: delete after 1 day (no B2 archive)"""
        mp4 = tmp_path / "final.mp4"
        mp4.write_bytes(b"\x00" * 1024)
        job = {
            "job_id": "free-old",
            "plan": "free",
            "output_path": str(mp4),
            "output_storage_tier": "local",
            "completed_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        }
        assert lifecycle.should_delete(job) is True

    def test_should_delete_archived_starter_after_30_days(self, lifecycle):
        """Starter archived job should delete after 30 days"""
        job = {
            "job_id": "arch-old",
            "plan": "starter",
            "output_storage_tier": "archived",
            "completed_at": (datetime.now(timezone.utc) - timedelta(days=38)).isoformat(),
        }
        assert lifecycle.should_delete(job) is True

    def test_should_not_delete_archived_within_retention(self, lifecycle, sample_job_archived):
        """35-day-old starter archived job should NOT delete yet (total window = 7+30=37 days)"""
        assert lifecycle.should_delete(sample_job_archived) is False

    def test_should_not_delete_already_deleted(self, lifecycle):
        """Already deleted job must not be processed again"""
        job = {
            "job_id": "deleted",
            "plan": "starter",
            "output_storage_tier": "deleted",
            "completed_at": (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(),
        }
        assert lifecycle.should_delete(job) is False


# ─────────────────────────────────────────────
# ARCHIVE OPERATION TESTS
# ─────────────────────────────────────────────

class TestArchiveOperation:

    def test_archive_local_file_to_b2(self, lifecycle, sample_job_old_local):
        """archive_to_b2 must upload file and return B2 URL"""
        with patch.object(lifecycle, '_upload_to_b2') as mock_upload:
            mock_upload.return_value = "https://b2.example.com/hezcast/job-old-001/final.mp4"
            result = lifecycle.archive_to_b2(sample_job_old_local)
        assert result.startswith("https://")
        assert "job-old-001" in result or mock_upload.called

    def test_archive_deletes_local_file_after_upload(self, lifecycle, sample_job_old_local):
        """After B2 upload, local file must be deleted"""
        local_path = sample_job_old_local["output_path"]
        assert Path(local_path).exists()
        with patch.object(lifecycle, '_upload_to_b2') as mock_upload:
            mock_upload.return_value = "https://b2.example.com/hezcast/final.mp4"
            lifecycle.archive_to_b2(sample_job_old_local)
        assert not Path(local_path).exists()

    def test_archive_nonexistent_file_raises(self, lifecycle):
        """Archiving a missing file must raise FileNotFoundError"""
        job = {
            "job_id": "missing",
            "plan": "starter",
            "output_path": "/nonexistent/final.mp4",
            "output_storage_tier": "local",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        with pytest.raises(FileNotFoundError):
            lifecycle.archive_to_b2(job)


# ─────────────────────────────────────────────
# DELETE OPERATION TESTS
# ─────────────────────────────────────────────

class TestDeleteOperation:

    def test_delete_from_b2(self, lifecycle, sample_job_archived):
        """delete_from_b2 must call B2 delete API"""
        with patch.object(lifecycle, '_delete_from_b2') as mock_del:
            mock_del.return_value = True
            result = lifecycle.delete_from_b2(sample_job_archived)
        assert mock_del.called
        assert result is True

    def test_delete_local_file(self, lifecycle, sample_job_old_local):
        """delete_local must remove file from disk"""
        local_path = sample_job_old_local["output_path"]
        assert Path(local_path).exists()
        lifecycle.delete_local(sample_job_old_local)
        assert not Path(local_path).exists()

    def test_delete_local_missing_file_does_not_raise(self, lifecycle):
        """Deleting already-missing local file must not raise"""
        job = {"output_path": "/nonexistent/final.mp4"}
        try:
            lifecycle.delete_local(job)
        except Exception as e:
            pytest.fail(f"delete_local raised unexpectedly: {e}")


# ─────────────────────────────────────────────
# AGE CALCULATION TESTS
# ─────────────────────────────────────────────

class TestAgeCalculation:

    def test_age_days_returns_float(self, lifecycle):
        """get_age_days must return float"""
        completed_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        result = lifecycle.get_age_days(completed_at)
        assert isinstance(result, float)

    def test_age_days_is_accurate(self, lifecycle):
        """Age should be approximately 5 days for 5-day-old job"""
        completed_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        result = lifecycle.get_age_days(completed_at)
        assert 4.9 <= result <= 5.1

    def test_age_days_zero_for_new_job(self, lifecycle):
        """Brand new job should have age near 0"""
        completed_at = datetime.now(timezone.utc).isoformat()
        result = lifecycle.get_age_days(completed_at)
        assert result < 0.1

    def test_age_days_handles_none(self, lifecycle):
        """None completed_at must return 0"""
        result = lifecycle.get_age_days(None)
        assert result == 0.0
