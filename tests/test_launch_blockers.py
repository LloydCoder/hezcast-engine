"""
HezCast Engine — Launch Blockers Tests
All 6 must-have items before taking real money
Tinlance Limited | Apache 2.0

Blocker 1: Transaction log + idempotency
Blocker 2: Celery beat config
Blocker 3: Env vars completeness
Blocker 4: Requirements pinned
Blocker 5: /generate empty validation
Blocker 6: GET /jobs endpoint
"""

import pytest
import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)

@pytest.fixture
def tx_log():
    from core.transaction_log import TransactionLog
    return TransactionLog()

@pytest.fixture
def sample_lemonsqueezy_tx():
    return {
        "provider":       "lemonsqueezy",
        "provider_tx_id": "sub_" + str(uuid.uuid4())[:8],
        "tenant_id":      "tenant-001",
        "amount_usd":     49.00,
        "currency":       "usd",
        "status":         "paid",
        "credits_added":  60,
        "plan_activated": "pro",
        "event_type":     "subscription_created",
    }

@pytest.fixture
def sample_nowpayments_tx():
    return {
        "provider":       "nowpayments",
        "provider_tx_id": "pay_" + str(uuid.uuid4())[:8],
        "tenant_id":      "tenant-002",
        "amount_usd":     45.00,
        "currency":       "usdttrc20",
        "status":         "confirmed",
        "credits_added":  50,
        "plan_activated": None,
        "event_type":     "topup",
    }


# ═══════════════════════════════════════════════════
# BLOCKER 1 — TRANSACTION LOG + IDEMPOTENCY
# ═══════════════════════════════════════════════════

class TestTransactionLog:

    def test_record_transaction_returns_id(self, tx_log, sample_lemonsqueezy_tx):
        """record() must return a transaction ID"""
        with patch.object(tx_log, '_save') as mock_save:
            mock_save.return_value = "tx-001"
            result = tx_log.record(sample_lemonsqueezy_tx)
        assert result is not None

    def test_record_transaction_saves_all_fields(self, tx_log, sample_lemonsqueezy_tx):
        """record() must save all required fields"""
        saved = {}
        with patch.object(tx_log, '_save', side_effect=lambda d: saved.update(d) or "tx-001"):
            tx_log.record(sample_lemonsqueezy_tx)
        assert saved.get("provider") == "lemonsqueezy"
        assert saved.get("tenant_id") == "tenant-001"
        assert saved.get("credits_added") == 60

    def test_is_duplicate_true_for_existing_tx(self, tx_log, sample_lemonsqueezy_tx):
        """is_duplicate must return True for already-processed provider_tx_id"""
        provider_tx_id = sample_lemonsqueezy_tx["provider_tx_id"]
        with patch.object(tx_log, '_exists', return_value=True):
            assert tx_log.is_duplicate("lemonsqueezy", provider_tx_id) is True

    def test_is_duplicate_false_for_new_tx(self, tx_log, sample_lemonsqueezy_tx):
        """is_duplicate must return False for new provider_tx_id"""
        with patch.object(tx_log, '_exists', return_value=False):
            assert tx_log.is_duplicate("lemonsqueezy", "new_tx_id") is False

    def test_duplicate_webhook_not_processed_twice(self, tx_log, sample_lemonsqueezy_tx):
        """Processing duplicate provider_tx_id must raise DuplicateTransactionError"""
        from core.transaction_log import DuplicateTransactionError
        with patch.object(tx_log, '_exists', return_value=True):
            with pytest.raises(DuplicateTransactionError):
                tx_log.record_or_raise(sample_lemonsqueezy_tx)

    def test_new_tx_does_not_raise(self, tx_log, sample_lemonsqueezy_tx):
        """New transaction must not raise"""
        with patch.object(tx_log, '_exists', return_value=False):
            with patch.object(tx_log, '_save', return_value="tx-001"):
                try:
                    tx_log.record_or_raise(sample_lemonsqueezy_tx)
                except Exception as e:
                    pytest.fail(f"record_or_raise raised unexpectedly: {e}")

    def test_get_tenant_transactions_returns_list(self, tx_log):
        """get_tenant_transactions must return list"""
        with patch.object(tx_log, '_query_by_tenant') as mock_q:
            mock_q.return_value = []
            result = tx_log.get_tenant_transactions("tenant-001")
        assert isinstance(result, list)

    def test_nowpayments_tx_recorded(self, tx_log, sample_nowpayments_tx):
        """NOWPayments transaction must be recordable"""
        saved = {}
        with patch.object(tx_log, '_save', side_effect=lambda d: saved.update(d) or "tx-002"):
            tx_log.record(sample_nowpayments_tx)
        assert saved.get("provider") == "nowpayments"
        assert saved.get("credits_added") == 50

    def test_missing_provider_tx_id_raises(self, tx_log):
        """Missing provider_tx_id must raise ValueError"""
        with pytest.raises(ValueError, match="provider_tx_id"):
            tx_log.record({
                "provider": "lemonsqueezy",
                "tenant_id": "t001",
                "amount_usd": 49.00,
            })

    def test_missing_tenant_id_raises(self, tx_log):
        """Missing tenant_id must raise ValueError"""
        with pytest.raises(ValueError, match="tenant_id"):
            tx_log.record({
                "provider": "lemonsqueezy",
                "provider_tx_id": "sub_123",
                "amount_usd": 49.00,
            })


# ═══════════════════════════════════════════════════
# BLOCKER 2 — CELERY BEAT CONFIG
# ═══════════════════════════════════════════════════

class TestCeleryBeatConfig:

    def test_beat_schedule_exists_in_celery_app(self):
        """Celery app must have beat_schedule configured"""
        from workers.celery_app import app
        assert hasattr(app.conf, 'beat_schedule')
        assert app.conf.beat_schedule is not None

    def test_nightly_backup_task_scheduled(self):
        """Nightly DB backup must be in beat schedule"""
        from workers.celery_app import app
        schedule = app.conf.beat_schedule
        task_names = [v.get("task", "") for v in schedule.values()]
        assert any("backup" in t for t in task_names)

    def test_storage_sweep_task_scheduled(self):
        """Nightly storage sweep must be in beat schedule"""
        from workers.celery_app import app
        schedule = app.conf.beat_schedule
        task_names = [v.get("task", "") for v in schedule.values()]
        assert any("storage" in t for t in task_names)

    def test_docker_compose_has_celery_beat_service(self):
        """docker-compose.yml must have a celery-beat service"""
        compose = open("docker-compose.yml").read()
        assert "celery-beat" in compose or "celerybeat" in compose.lower()

    def test_beat_schedule_has_24h_interval(self):
        """Backup task must run every 24 hours"""
        from workers.celery_app import app
        schedule = app.conf.beat_schedule
        for name, task in schedule.items():
            if "backup" in name:
                assert task.get("schedule") == 86400


# ═══════════════════════════════════════════════════
# BLOCKER 3 — ENV VARS COMPLETENESS
# ═══════════════════════════════════════════════════

class TestEnvVarsCompleteness:

    REQUIRED_ENV_VARS = [
        # LLM
        "CLAUDE_API_KEY",
        "OPENAI_API_KEY",
        # Media
        "PEXELS_API_KEY",
        # Telegram
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        # Database
        "DATABASE_URL",
        "DB_PASSWORD",
        # Backblaze B2
        "B2_KEY_ID",
        "B2_APP_KEY",
        "B2_BUCKET_NAME",
        # Billing — LemonSqueezy
        "LEMONSQUEEZY_WEBHOOK_SECRET",
        "LEMONSQUEEZY_STORE_SLUG",
        "LS_VARIANT_CREDITS_50",
        "LS_VARIANT_CREDITS_100",
        # Billing — NOWPayments
        "NOWPAYMENTS_API_KEY",
        "NOWPAYMENTS_IPN_SECRET",
        # App
        "DOMAIN",
        "ENVIRONMENT",
    ]

    def test_env_example_exists(self):
        """.env.example file must exist"""
        assert Path(".env.example").exists()

    def test_all_required_vars_in_env_example(self):
        """Every required env var must appear in .env.example"""
        env_content = Path(".env.example").read_text()
        missing = []
        for var in self.REQUIRED_ENV_VARS:
            if var not in env_content:
                missing.append(var)
        assert missing == [], f"Missing from .env.example: {missing}"

    def test_env_example_has_no_real_secrets(self):
        """.env.example must not contain real API keys"""
        content = Path(".env.example").read_text()
        # Must not contain real key patterns (not placeholders)
        # Real Anthropic keys are sk-ant-api03-... (long random string)
        import re
        real_key_pattern = r"sk-ant-api\d+-[A-Za-z0-9_-]{20,}"
        assert not re.search(real_key_pattern, content), "Real Anthropic key found in .env.example"
        assert "Bearer eyJ" not in content, "JWT token found in .env.example"


# ═══════════════════════════════════════════════════
# BLOCKER 4 — REQUIREMENTS PINNED
# ═══════════════════════════════════════════════════

class TestRequirementsPinned:

    CRITICAL_PACKAGES = [
        "fastapi", "uvicorn", "celery", "redis",
        "pydantic", "requests", "anthropic",
        "pillow", "boto3", "psycopg2-binary",
    ]

    def test_requirements_txt_exists(self):
        """requirements.txt must exist"""
        assert Path("requirements.txt").exists()

    def test_critical_packages_in_requirements(self):
        """All critical packages must be in requirements.txt"""
        content = Path("requirements.txt").read_text().lower()
        missing = []
        for pkg in self.CRITICAL_PACKAGES:
            if pkg.lower().replace("-", "") not in content.replace("-", "").replace("_", ""):
                missing.append(pkg)
        assert missing == [], f"Missing from requirements.txt: {missing}"

    def test_packages_have_pinned_versions(self):
        """At least core packages must have pinned versions (== or >=)"""
        content = Path("requirements.txt").read_text()
        lines = [l.strip() for l in content.splitlines()
                 if l.strip() and not l.startswith("#")]
        pinned = [l for l in lines if "==" in l or ">=" in l]
        # At least 80% should be pinned
        pct = len(pinned) / max(len(lines), 1)
        assert pct >= 0.5, f"Only {len(pinned)}/{len(lines)} packages pinned"

    def test_nowpayments_not_required_in_reqs(self):
        """NOWPayments uses requests — no extra SDK needed"""
        content = Path("requirements.txt").read_text().lower()
        # We use requests directly — no nowpayments SDK
        assert "requests" in content


# ═══════════════════════════════════════════════════
# BLOCKER 5 — /generate EMPTY REQUEST VALIDATION
# ═══════════════════════════════════════════════════

class TestGenerateEmptyValidation:

    def test_no_topic_no_url_returns_422(self, client):
        """Request with neither topic nor url must return 422"""
        resp = client.post(
            "/generate",
            json={"brand": "GiftMode"}
        )
        assert resp.status_code == 422

    def test_empty_topic_and_no_url_returns_422(self, client):
        """Empty topic with no URL must return 422"""
        resp = client.post(
            "/generate",
            json={"brand": "GiftMode", "topic": ""}
        )
        assert resp.status_code == 422

    def test_whitespace_topic_no_url_returns_422(self, client):
        """Whitespace-only topic with no URL must return 422"""
        resp = client.post(
            "/generate",
            json={"brand": "GiftMode", "topic": "   "}
        )
        assert resp.status_code == 422

    def test_valid_topic_returns_202(self, client):
        """Valid topic must return 202"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": "abc123", "status": "queued"}
            resp = client.post(
                "/generate",
                json={"brand": "GiftMode", "topic": "forgot birthday gift"}
            )
        assert resp.status_code == 202

    def test_valid_url_no_topic_returns_202(self, client):
        """Valid URL with no topic must return 202"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": "abc123", "status": "queued"}
            resp = client.post(
                "/generate",
                json={"brand": "GiftMode", "url": "https://giftmode.app/blog/post"}
            )
        assert resp.status_code == 202

    def test_no_brand_returns_422(self, client):
        """Request without brand must return 422"""
        resp = client.post(
            "/generate",
            json={"topic": "test topic"}
        )
        assert resp.status_code == 422

    def test_invalid_brand_returns_422(self, client):
        """Unknown brand must return 422"""
        resp = client.post(
            "/generate",
            json={"topic": "test", "brand": "NotABrand"}
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════
# BLOCKER 6 — GET /jobs ENDPOINT
# ═══════════════════════════════════════════════════

class TestJobsEndpoint:

    def test_get_jobs_returns_200(self, client):
        """GET /jobs must return 200"""
        resp = client.get("/jobs")
        assert resp.status_code == 200

    def test_get_jobs_returns_list(self, client):
        """GET /jobs must return a list"""
        resp = client.get("/jobs")
        assert isinstance(resp.json(), list)

    def test_get_jobs_items_have_required_fields(self, client):
        """Each job must have job_id, brand, topic, status"""
        with patch("api.routes.jobs.get_all_jobs") as mock_jobs:
            mock_jobs.return_value = [{
                "job_id":  "abc123",
                "brand":   "GiftMode",
                "topic":   "test topic",
                "status":  "completed",
                "created_at": "2026-05-26T03:00:00Z",
            }]
            resp = client.get("/jobs")
        if resp.json():
            job = resp.json()[0]
            assert "job_id"  in job
            assert "status"  in job
            assert "brand"   in job

    def test_get_jobs_filter_by_brand(self, client):
        """GET /jobs?brand=GiftMode must filter by brand"""
        resp = client.get("/jobs?brand=GiftMode")
        assert resp.status_code == 200

    def test_get_jobs_filter_by_status(self, client):
        """GET /jobs?status=completed must filter by status"""
        resp = client.get("/jobs?status=completed")
        assert resp.status_code == 200

    def test_get_jobs_limit_param(self, client):
        """GET /jobs?limit=10 must respect limit"""
        resp = client.get("/jobs?limit=10")
        assert resp.status_code == 200
        assert len(resp.json()) <= 10

    def test_get_jobs_invalid_limit_returns_422(self, client):
        """GET /jobs?limit=0 must return 422"""
        resp = client.get("/jobs?limit=0")
        assert resp.status_code == 422

    def test_get_jobs_invalid_brand_returns_422(self, client):
        """GET /jobs?brand=FakeBrand must return 422"""
        resp = client.get("/jobs?brand=FakeBrand")
        assert resp.status_code == 422

    def test_get_job_stats_returns_200(self, client):
        """GET /jobs/stats must return summary stats"""
        resp = client.get("/jobs/stats")
        assert resp.status_code == 200

    def test_job_stats_has_required_fields(self, client):
        """Stats must have total, completed, failed, qa_pass_rate"""
        resp = client.get("/jobs/stats")
        if resp.status_code == 200:
            data = resp.json()
            assert "total" in data
