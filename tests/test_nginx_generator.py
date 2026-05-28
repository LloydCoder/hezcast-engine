"""
HezCast Engine — Nginx Configuration Tests
Gap 3: Subdomain routing + security headers
Tinlance Limited | Apache 2.0

Tests for:
  - Nginx config generation correctness
  - Subdomain routing rules
  - Admin IP restriction
  - Security headers
  - SSL/TLS configuration
"""

import pytest
import re
from pathlib import Path


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def nginx_generator():
    from deploy.nginx_generator import NginxConfigGenerator
    return NginxConfigGenerator()

@pytest.fixture
def base_config():
    return {
        "domain":       "hezcast.com",
        "api_port":     8503,
        "app_url":      "https://hezcast-saas.vercel.app",
        "admin_ip":     "185.10.20.30",
        "email":        "nwachukwuchinaemerem8@gmail.com",
    }


# ─────────────────────────────────────────────
# SUBDOMAIN ROUTING TESTS
# ─────────────────────────────────────────────

class TestSubdomainRouting:

    def test_api_subdomain_proxies_to_fastapi(self, nginx_generator, base_config):
        """api.hezcast.com must proxy to FastAPI port"""
        config = nginx_generator.generate(base_config)
        assert "api.hezcast.com" in config
        assert "8503" in config

    def test_app_subdomain_proxies_to_vercel(self, nginx_generator, base_config):
        """app.hezcast.com must proxy to Vercel URL"""
        config = nginx_generator.generate(base_config)
        assert "app.hezcast.com" in config

    def test_admin_subdomain_present(self, nginx_generator, base_config):
        """admin.hezcast.com block must be present"""
        config = nginx_generator.generate(base_config)
        assert "admin.hezcast.com" in config

    def test_www_redirects_to_apex(self, nginx_generator, base_config):
        """www.hezcast.com must redirect to hezcast.com"""
        config = nginx_generator.generate(base_config)
        assert "www.hezcast.com" in config
        assert "301" in config

    def test_http_redirects_to_https(self, nginx_generator, base_config):
        """HTTP must redirect to HTTPS"""
        config = nginx_generator.generate(base_config)
        assert "return 301 https" in config or "https://" in config


# ─────────────────────────────────────────────
# ADMIN IP RESTRICTION TESTS
# ─────────────────────────────────────────────

class TestAdminIPRestriction:

    def test_admin_allows_configured_ip(self, nginx_generator, base_config):
        """Admin block must allow the configured IP"""
        config = nginx_generator.generate(base_config)
        assert "185.10.20.30" in config

    def test_admin_denies_all_others(self, nginx_generator, base_config):
        """Admin block must have deny all directive"""
        config = nginx_generator.generate(base_config)
        # Find the HTTPS admin block (not the HTTP redirect block)
        admin_marker = "IP RESTRICTION"
        admin_section = config[config.find(admin_marker):]
        assert "deny" in admin_section and "all" in admin_section

    def test_admin_has_allow_before_deny(self, nginx_generator, base_config):
        """allow directive must appear before deny all"""
        config = nginx_generator.generate(base_config)
        admin_marker = "IP RESTRICTION"
        section  = config[config.find(admin_marker):config.find(admin_marker) + 300]
        allow_pos = section.find("allow")
        deny_pos  = section.find("deny")
        assert allow_pos != -1
        assert deny_pos != -1
        assert allow_pos < deny_pos

    def test_admin_ip_change_updates_config(self, nginx_generator, base_config):
        """Changing admin IP must update the allow directive"""
        base_config["admin_ip"] = "10.20.30.40"
        config = nginx_generator.generate(base_config)
        assert "10.20.30.40" in config


# ─────────────────────────────────────────────
# SECURITY HEADERS TESTS
# ─────────────────────────────────────────────

class TestSecurityHeaders:

    def test_x_frame_options_present(self, nginx_generator, base_config):
        """X-Frame-Options header must be present"""
        config = nginx_generator.generate(base_config)
        assert "X-Frame-Options" in config

    def test_x_content_type_options_present(self, nginx_generator, base_config):
        """X-Content-Type-Options header must be present"""
        config = nginx_generator.generate(base_config)
        assert "X-Content-Type-Options" in config

    def test_hsts_header_present(self, nginx_generator, base_config):
        """HSTS header must be present for HTTPS"""
        config = nginx_generator.generate(base_config)
        assert "Strict-Transport-Security" in config

    def test_no_server_version_leak(self, nginx_generator, base_config):
        """server_tokens must be off"""
        config = nginx_generator.generate(base_config)
        assert "server_tokens off" in config

    def test_cors_headers_for_api(self, nginx_generator, base_config):
        """API subdomain must include CORS headers"""
        config = nginx_generator.generate(base_config)
        api_section = config[config.find("api.hezcast.com"):]
        assert "Access-Control" in api_section or "cors" in api_section.lower()


# ─────────────────────────────────────────────
# SSL CONFIGURATION TESTS
# ─────────────────────────────────────────────

class TestSSLConfig:

    def test_ssl_certificate_path_present(self, nginx_generator, base_config):
        """SSL certificate path must reference hezcast.com"""
        config = nginx_generator.generate(base_config)
        assert "ssl_certificate" in config
        assert "hezcast.com" in config

    def test_ssl_protocols_are_modern(self, nginx_generator, base_config):
        """Must only allow TLS 1.2 and 1.3"""
        config = nginx_generator.generate(base_config)
        assert "TLSv1.2" in config
        assert "TLSv1.3" in config
        assert "TLSv1.0" not in config
        assert "TLSv1.1" not in config

    def test_certbot_webroot_path_present(self, nginx_generator, base_config):
        """Certbot well-known path must be configured"""
        config = nginx_generator.generate(base_config)
        assert ".well-known" in config or "certbot" in config.lower()


# ─────────────────────────────────────────────
# CONFIG FILE GENERATION TESTS
# ─────────────────────────────────────────────

class TestConfigFileGeneration:

    def test_save_config_creates_file(self, nginx_generator, base_config, tmp_path):
        """save_config must write file to disk"""
        out = str(tmp_path / "hezcast.conf")
        nginx_generator.save_config(base_config, out)
        assert Path(out).exists()

    def test_saved_config_is_non_empty(self, nginx_generator, base_config, tmp_path):
        """Saved config file must be non-empty"""
        out = str(tmp_path / "hezcast.conf")
        nginx_generator.save_config(base_config, out)
        assert Path(out).stat().st_size > 100

    def test_generate_returns_string(self, nginx_generator, base_config):
        """generate must return a string"""
        result = nginx_generator.generate(base_config)
        assert isinstance(result, str)
        assert len(result) > 100
