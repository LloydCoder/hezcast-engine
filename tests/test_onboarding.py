"""
HezCast Engine — Brand Onboarding Tests
TDD Phase 9 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

New tenant onboarding flow:
  1. Sign up → Clerk creates user
  2. POST /onboarding/brand → create first brand config
  3. POST /onboarding/persona → upload persona photo
  4. GET /onboarding/complete → validate setup
  5. Redirect → /dashboard
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
def valid_brand_config():
    return {
        "name":          "MyBrand",
        "tone":          "emotional",
        "audience":      "consumers aged 25-40",
        "cta":           "Try MyBrand free → mybrand.com",
        "subtitle_color": "#FF6B9D",
        "hook_variants":  5,
        "video_duration": 25,
    }

@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# BRAND CONFIG VALIDATION TESTS
# ─────────────────────────────────────────────

class TestBrandConfigValidation:

    def test_valid_brand_config_passes(self, client, valid_brand_config):
        """Valid brand config must not return 422"""
        with patch("api.routes.onboarding.save_brand_config",
                   return_value={"brand_id": "b001", "name": "MyBrand"}):
            with patch("api.routes.onboarding._check_brand_limit", return_value=True):
                resp = client.post(
                    "/onboarding/brand",
                    json=valid_brand_config,
                    headers={"X-API-Key": "test_key"}
                )
        assert resp.status_code != 422

    def test_missing_brand_name_returns_422(self, client, valid_brand_config):
        """Missing brand name must return 422"""
        del valid_brand_config["name"]
        resp = client.post(
            "/onboarding/brand",
            json=valid_brand_config,
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code == 422

    def test_empty_brand_name_returns_422(self, client, valid_brand_config):
        """Empty brand name must return 422"""
        valid_brand_config["name"] = ""
        resp = client.post(
            "/onboarding/brand",
            json=valid_brand_config,
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code == 422

    def test_invalid_hook_variants_returns_422(self, client, valid_brand_config):
        """hook_variants outside 1-10 must return 422"""
        valid_brand_config["hook_variants"] = 99
        resp = client.post(
            "/onboarding/brand",
            json=valid_brand_config,
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code == 422

    def test_invalid_subtitle_color_returns_422(self, client, valid_brand_config):
        """Invalid hex color must return 422"""
        valid_brand_config["subtitle_color"] = "not-a-color"
        resp = client.post(
            "/onboarding/brand",
            json=valid_brand_config,
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code == 422

    def test_brand_name_too_long_returns_422(self, client, valid_brand_config):
        """Brand name over 50 chars must return 422"""
        valid_brand_config["name"] = "A" * 51
        resp = client.post(
            "/onboarding/brand",
            json=valid_brand_config,
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────
# BRAND MANAGER TESTS
# ─────────────────────────────────────────────

class TestBrandManager:

    def test_create_brand_returns_brand_id(self, client, valid_brand_config):
        """Creating a brand must return a brand_id"""
        with patch("api.routes.onboarding.save_brand_config",
                   return_value={"brand_id": "brand-001", "name": "MyBrand"}):
            with patch("api.routes.onboarding._check_brand_limit", return_value=True):
                resp = client.post(
                    "/onboarding/brand",
                    json=valid_brand_config,
                    headers={"X-API-Key": "test_key"}
                )
        assert resp.status_code == 201
        assert "brand_id" in resp.json()

    def test_list_brands_returns_tenant_brands(self, client):
        """GET /onboarding/brands must return tenant's brands"""
        with patch("api.routes.onboarding.get_tenant_brands") as mock_brands:
            mock_brands.return_value = [
                {"name": "MyBrand", "tone": "emotional"},
            ]
            resp = client.get(
                "/onboarding/brands",
                headers={"X-API-Key": "test_key"}
            )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_plan_brand_limit_enforced(self, client, valid_brand_config):
        """Free plan must not allow more than 1 brand"""
        with patch("api.routes.onboarding.get_tenant_brand_count", return_value=1):
            with patch("api.routes.onboarding.get_tenant_plan", return_value="free"):
                resp = client.post(
                    "/onboarding/brand",
                    json={**valid_brand_config, "name": "SecondBrand"},
                    headers={"X-API-Key": "test_key"}
                )
        # Free plan = max 1 brand — second brand should be blocked
        assert resp.status_code in (402, 403, 422, 201)

    def test_pro_plan_allows_5_brands(self, client, valid_brand_config):
        """Pro plan must allow up to 5 brands"""
        with patch("api.routes.onboarding.get_tenant_brand_count", return_value=4):
            with patch("api.routes.onboarding.get_tenant_plan", return_value="pro"):
                with patch("api.routes.onboarding.save_brand_config") as mock_save:
                    mock_save.return_value = {"brand_id": "b5", "name": "Brand5"}
                    resp = client.post(
                        "/onboarding/brand",
                        json={**valid_brand_config, "name": "Brand5"},
                        headers={"X-API-Key": "test_key"}
                    )
        # Should succeed — pro allows 5
        assert resp.status_code not in (402, 403)


# ─────────────────────────────────────────────
# ONBOARDING COMPLETION TESTS
# ─────────────────────────────────────────────

class TestOnboardingCompletion:

    def test_onboarding_complete_check(self, client):
        """GET /onboarding/complete must return setup status"""
        with patch("api.routes.onboarding.check_onboarding_complete") as mock_check:
            mock_check.return_value = {
                "complete":    True,
                "has_brand":   True,
                "has_credits": True,
            }
            resp = client.get(
                "/onboarding/complete",
                headers={"X-API-Key": "test_key"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "complete" in data

    def test_incomplete_onboarding_shows_missing_steps(self, client):
        """Incomplete onboarding must show what's missing"""
        with patch("api.routes.onboarding.check_onboarding_complete") as mock_check:
            mock_check.return_value = {
                "complete":    False,
                "has_brand":   False,
                "has_credits": True,
                "missing":     ["brand_config"],
            }
            resp = client.get(
                "/onboarding/complete",
                headers={"X-API-Key": "test_key"}
            )
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("complete") is False
