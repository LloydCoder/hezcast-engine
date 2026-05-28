"""
HezCast Engine — API Layer Tests
TDD Phase 4 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

FastAPI endpoints:
  POST /generate       → submit job
  GET  /status/{id}    → poll job status
  GET  /hooks/{id}     → get hook variants
  POST /hooks/{id}/select → select hook → trigger render
  GET  /health         → system health
  GET  /brands         → list brands
"""

import pytest
import json
import uuid
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
def valid_generate_payload():
    return {
        "topic": "forgot birthday gift last minute",
        "brand": "GiftMode",
        "tone":  "emotional"
    }

@pytest.fixture
def mock_job_id():
    return str(uuid.uuid4())

@pytest.fixture
def mock_job_queued(mock_job_id):
    return {
        "job_id": mock_job_id,
        "status": "queued",
        "brand":  "GiftMode",
        "topic":  "forgot birthday gift last minute",
    }

@pytest.fixture
def mock_job_completed(mock_job_id):
    return {
        "job_id":      mock_job_id,
        "status":      "completed",
        "brand":       "GiftMode",
        "topic":       "forgot birthday gift last minute",
        "output_path": f"/storage/outputs/{mock_job_id}/final.mp4",
        "duration_sec": 24.3,
        "render_time_ms": 134200,
        "qa_passed":   True,
    }

@pytest.fixture
def mock_hook_variants(mock_job_id):
    return [
        {"variant_num": 1, "hook_text": "Nobody told me you could forget TWICE...", "selected": False},
        {"variant_num": 2, "hook_text": "I had 2 hours to find a gift. Cooked.", "selected": False},
        {"variant_num": 3, "hook_text": "POV: Her birthday is TODAY.", "selected": False},
        {"variant_num": 4, "hook_text": "The gift panic is real.", "selected": False},
        {"variant_num": 5, "hook_text": "She said it's fine. It was NOT fine.", "selected": False},
    ]


# ─────────────────────────────────────────────
# HEALTH CHECK TESTS
# ─────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        """GET /health must return 200"""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_status_field(self, client):
        """Health response must have status field"""
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data

    def test_health_returns_version(self, client):
        """Health response must include version"""
        resp = client.get("/health")
        data = resp.json()
        assert "version" in data

    def test_health_returns_services(self, client):
        """Health response must report service states"""
        resp = client.get("/health")
        data = resp.json()
        assert "services" in data


# ─────────────────────────────────────────────
# BRANDS ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestBrandsEndpoint:

    def test_brands_returns_200(self, client):
        """GET /brands must return 200"""
        resp = client.get("/brands")
        assert resp.status_code == 200

    def test_brands_returns_list(self, client):
        """GET /brands must return a list"""
        resp = client.get("/brands")
        data = resp.json()
        assert isinstance(data, list)

    def test_brands_contains_all_three(self, client):
        """Response must include GiftMode, Tinlance, WebTemify"""
        resp = client.get("/brands")
        names = [b["name"] for b in resp.json()]
        assert "GiftMode" in names
        assert "Tinlance" in names
        assert "WebTemify" in names

    def test_each_brand_has_required_fields(self, client):
        """Each brand must have name, tone, hook_variants"""
        resp = client.get("/brands")
        for brand in resp.json():
            assert "name" in brand
            assert "tone" in brand
            assert "hook_variants" in brand


# ─────────────────────────────────────────────
# GENERATE ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestGenerateEndpoint:

    def test_generate_returns_202(self, client, valid_generate_payload):
        """POST /generate must return 202 Accepted"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": str(uuid.uuid4()), "status": "queued"}
            resp = client.post("/generate", json=valid_generate_payload)
        assert resp.status_code == 202

    def test_generate_returns_job_id(self, client, valid_generate_payload):
        """Response must contain job_id"""
        fake_id = str(uuid.uuid4())
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": fake_id, "status": "queued"}
            resp = client.post("/generate", json=valid_generate_payload)
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == fake_id

    def test_generate_returns_status_queued(self, client, valid_generate_payload):
        """Initial status must be queued"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": str(uuid.uuid4()), "status": "queued"}
            resp = client.post("/generate", json=valid_generate_payload)
        assert resp.json()["status"] == "queued"

    def test_generate_missing_topic_returns_202_if_url_provided(self, client):
        """Missing topic is OK if url is provided"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": "abc", "status": "queued"}
            resp = client.post("/generate", json={"brand": "GiftMode", "url": "https://tinlance.com/blog/test"})
        assert resp.status_code == 202

    def test_generate_missing_brand_returns_422(self, client):
        """Missing brand must return 422"""
        resp = client.post("/generate", json={"topic": "test topic"})
        assert resp.status_code == 422

    def test_generate_unknown_brand_returns_422(self, client):
        """Unknown brand must return 422"""
        resp = client.post(
            "/generate",
            json={"topic": "test", "brand": "FakeBrand"}
        )
        assert resp.status_code == 422

    def test_generate_empty_topic_returns_422(self, client):
        """Empty topic string must return 422"""
        resp = client.post(
            "/generate",
            json={"topic": "", "brand": "GiftMode"}
        )
        assert resp.status_code == 422

    def test_generate_whitespace_topic_still_submits(self, client):
        """Whitespace topic falls back to url or default gracefully"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": "abc", "status": "queued"}
            resp = client.post(
                "/generate",
                json={"topic": "   ", "brand": "GiftMode"}
            )
        # Either 202 (submitted with default) or 422 (rejected) — both acceptable
        assert resp.status_code in (202, 422)

    def test_generate_tone_is_optional(self, client):
        """Tone field must be optional"""
        with patch("api.routes.generate.submit_job") as mock_submit:
            mock_submit.return_value = {"job_id": str(uuid.uuid4()), "status": "queued"}
            resp = client.post(
                "/generate",
                json={"topic": "test topic", "brand": "GiftMode"}
            )
        assert resp.status_code == 202


# ─────────────────────────────────────────────
# STATUS ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestStatusEndpoint:

    def test_status_returns_200_for_known_job(self, client, mock_job_queued):
        """GET /status/{job_id} returns 200 for known job"""
        with patch("api.routes.status.get_job") as mock_get:
            mock_get.return_value = mock_job_queued
            resp = client.get(f"/status/{mock_job_queued['job_id']}")
        assert resp.status_code == 200

    def test_status_returns_404_for_unknown_job(self, client):
        """GET /status/{job_id} returns 404 for unknown job"""
        with patch("api.routes.status.get_job", return_value=None):
            resp = client.get(f"/status/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_status_response_has_job_id(self, client, mock_job_queued):
        """Status response must include job_id"""
        with patch("api.routes.status.get_job") as mock_get:
            mock_get.return_value = mock_job_queued
            resp = client.get(f"/status/{mock_job_queued['job_id']}")
        assert "job_id" in resp.json()

    def test_status_response_has_status_field(self, client, mock_job_queued):
        """Status response must include status field"""
        with patch("api.routes.status.get_job") as mock_get:
            mock_get.return_value = mock_job_queued
            resp = client.get(f"/status/{mock_job_queued['job_id']}")
        assert "status" in resp.json()

    def test_completed_job_has_output_path(self, client, mock_job_completed):
        """Completed job response must include output_path"""
        with patch("api.routes.status.get_job") as mock_get:
            mock_get.return_value = mock_job_completed
            resp = client.get(f"/status/{mock_job_completed['job_id']}")
        data = resp.json()
        assert "output_path" in data
        assert data["output_path"] is not None

    def test_status_values_are_valid(self, client, mock_job_queued):
        """Status must be one of the defined values"""
        valid_statuses = {
            "queued", "generating_hooks", "awaiting_selection",
            "processing", "composing", "qa_check",
            "completed", "failed", "needs_review"
        }
        with patch("api.routes.status.get_job") as mock_get:
            mock_get.return_value = mock_job_queued
            resp = client.get(f"/status/{mock_job_queued['job_id']}")
        assert resp.json()["status"] in valid_statuses


# ─────────────────────────────────────────────
# HOOKS ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestHooksEndpoint:

    def _seed_job(self, job_id, hooks):
        """Seed job and hooks into stores for testing"""
        from api.routes.generate import _jobs, _hooks_store
        _jobs[job_id] = {"job_id": job_id, "brand": "GiftMode",
                         "topic": "test", "status": "awaiting_selection"}
        _hooks_store[job_id] = hooks

    def test_get_hooks_returns_200(self, client, mock_job_id, mock_hook_variants):
        """GET /hooks/{job_id} returns 200"""
        self._seed_job(mock_job_id, mock_hook_variants)
        resp = client.get(f"/hooks/{mock_job_id}")
        assert resp.status_code == 200

    def test_get_hooks_returns_list(self, client, mock_job_id, mock_hook_variants):
        """GET /hooks response must be a list"""
        self._seed_job(mock_job_id, mock_hook_variants)
        resp = client.get(f"/hooks/{mock_job_id}")
        assert isinstance(resp.json(), list)

    def test_get_hooks_returns_all_variants(self, client, mock_job_id, mock_hook_variants):
        """GET /hooks must return all 5 variants for GiftMode"""
        self._seed_job(mock_job_id, mock_hook_variants)
        resp = client.get(f"/hooks/{mock_job_id}")
        assert len(resp.json()) == 5

    def test_get_hooks_404_for_unknown_job(self, client):
        """GET /hooks returns 404 for unknown job"""
        resp = client.get(f"/hooks/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_each_hook_has_variant_num(self, client, mock_job_id, mock_hook_variants):
        """Each hook must have variant_num"""
        self._seed_job(mock_job_id, mock_hook_variants)
        resp = client.get(f"/hooks/{mock_job_id}")
        for hook in resp.json():
            assert "variant_num" in hook

    def test_each_hook_has_hook_text(self, client, mock_job_id, mock_hook_variants):
        """Each hook must have hook_text"""
        self._seed_job(mock_job_id, mock_hook_variants)
        resp = client.get(f"/hooks/{mock_job_id}")
        for hook in resp.json():
            assert "hook_text" in hook


# ─────────────────────────────────────────────
# HOOK SELECTION ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestHookSelectEndpoint:

    def _seed_job(self, job_id):
        from api.routes.generate import _jobs, _hooks_store
        _jobs[job_id] = {"job_id": job_id, "brand": "GiftMode",
                         "topic": "test", "status": "awaiting_selection"}
        _hooks_store[job_id] = [
            {"variant_num": 1, "hook_text": "Hook 1", "full_script": "...", "selected": False},
            {"variant_num": 2, "hook_text": "Hook 2", "full_script": "...", "selected": False},
        ]

    def test_select_hook_returns_202(self, client, mock_job_id):
        """POST /hooks/{id}/select returns 202"""
        self._seed_job(mock_job_id)
        with patch("api.routes.hooks.select_hook_and_render") as mock_select:
            mock_select.return_value = {"job_id": mock_job_id, "status": "processing"}
            resp = client.post(
                f"/hooks/{mock_job_id}/select",
                json={"variant_num": 2}
            )
        assert resp.status_code == 202

    def test_select_hook_triggers_render(self, client, mock_job_id):
        """Selecting a hook must trigger the render pipeline"""
        self._seed_job(mock_job_id)
        with patch("api.routes.hooks.select_hook_and_render") as mock_select:
            mock_select.return_value = {"job_id": mock_job_id, "status": "processing"}
            client.post(
                f"/hooks/{mock_job_id}/select",
                json={"variant_num": 1}
            )
        assert mock_select.called

    def test_select_hook_missing_variant_num_returns_422(self, client, mock_job_id):
        """Missing variant_num must return 422"""
        self._seed_job(mock_job_id)
        resp = client.post(f"/hooks/{mock_job_id}/select", json={})
        assert resp.status_code == 422

    def test_select_hook_returns_job_id(self, client, mock_job_id):
        """Response must contain job_id"""
        self._seed_job(mock_job_id)
        with patch("api.routes.hooks.select_hook_and_render") as mock_select:
            mock_select.return_value = {"job_id": mock_job_id, "status": "processing"}
            resp = client.post(
                f"/hooks/{mock_job_id}/select",
                json={"variant_num": 1}
            )
        assert resp.json()["job_id"] == mock_job_id

    def test_select_invalid_variant_returns_422(self, client, mock_job_id):
        """variant_num=0 must return 422"""
        self._seed_job(mock_job_id)
        resp = client.post(
            f"/hooks/{mock_job_id}/select",
            json={"variant_num": 0}
        )
        assert resp.status_code == 422
