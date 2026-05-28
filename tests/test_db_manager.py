"""
HezCast Engine — Database Migration Tests
Gap 1: External Database (Neon/Postgres)
Tinlance Limited | Apache 2.0

Tests for:
  - DB connection validation
  - Schema migration runner
  - pgvector extension check
  - Connection pool health
"""

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def db_config_local():
    return {
        "host":     "localhost",
        "port":     5432,
        "database": "hezcast",
        "user":     "hezcast_app",
        "password": "test_password",
        "sslmode":  "disable",
    }

@pytest.fixture
def db_config_neon():
    return {
        "host":     "ep-cool-star-123.us-east-2.aws.neon.tech",
        "port":     5432,
        "database": "hezcastdb",
        "user":     "hezcast_app",
        "password": "neon_password_xyz",
        "sslmode":  "require",
    }

@pytest.fixture
def db_manager():
    from database.db_manager import DatabaseManager
    return DatabaseManager()


# ─────────────────────────────────────────────
# CONNECTION URL TESTS
# ─────────────────────────────────────────────

class TestConnectionURL:

    def test_build_local_connection_url(self, db_manager, db_config_local):
        """Local connection URL must not require SSL"""
        url = db_manager.build_connection_url(db_config_local)
        assert "localhost" in url
        assert "hezcast" in url
        assert url.startswith("postgresql://")

    def test_build_neon_connection_url_requires_ssl(self, db_manager, db_config_neon):
        """Neon connection URL must include sslmode=require"""
        url = db_manager.build_connection_url(db_config_neon)
        assert "sslmode=require" in url
        assert "neon.tech" in url

    def test_connection_url_includes_credentials(self, db_manager, db_config_local):
        """Connection URL must include user credentials"""
        url = db_manager.build_connection_url(db_config_local)
        assert "hezcast_app" in url

    def test_missing_host_raises(self, db_manager):
        """Missing host must raise ValueError"""
        with pytest.raises(ValueError, match="host"):
            db_manager.build_connection_url({
                "port": 5432, "database": "hezcast",
                "user": "user", "password": "pass"
            })

    def test_missing_database_raises(self, db_manager):
        """Missing database name must raise ValueError"""
        with pytest.raises(ValueError, match="database"):
            db_manager.build_connection_url({
                "host": "localhost", "port": 5432,
                "user": "user", "password": "pass"
            })

    def test_neon_url_from_env(self, db_manager, monkeypatch):
        """Must parse Neon DATABASE_URL from environment variable"""
        neon_url = "postgresql://user:pass@ep-cool-star.neon.tech/hezcastdb?sslmode=require"
        monkeypatch.setenv("DATABASE_URL", neon_url)
        url = db_manager.get_database_url()
        assert "neon.tech" in url


# ─────────────────────────────────────────────
# MIGRATION TESTS
# ─────────────────────────────────────────────

class TestMigrations:

    def test_migration_runner_returns_success(self, db_manager):
        """run_migrations must return success result"""
        with patch.object(db_manager, '_execute_sql') as mock_exec:
            mock_exec.return_value = True
            result = db_manager.run_migrations("database/schemas.sql")
        assert result["success"] is True

    def test_migration_reads_sql_file(self, db_manager):
        """run_migrations must read the SQL file"""
        with patch.object(db_manager, '_execute_sql') as mock_exec:
            mock_exec.return_value = True
            with patch("builtins.open", mock_open_sql()):
                db_manager.run_migrations("database/schemas.sql")
        assert mock_exec.called

    def test_migration_on_connection_failure_raises(self, db_manager):
        """Migration must raise on DB connection failure"""
        with patch.object(db_manager, '_execute_sql', side_effect=Exception("Connection refused")):
            with pytest.raises(Exception, match="Connection"):
                db_manager.run_migrations("database/schemas.sql")

    def test_pgvector_extension_check(self, db_manager):
        """Must verify pgvector extension is installed"""
        with patch.object(db_manager, '_query') as mock_q:
            mock_q.return_value = [{"extname": "vector"}]
            result = db_manager.check_pgvector()
        assert result is True

    def test_pgvector_missing_returns_false(self, db_manager):
        """Must return False when pgvector not installed"""
        with patch.object(db_manager, '_query') as mock_q:
            mock_q.return_value = []
            result = db_manager.check_pgvector()
        assert result is False


# ─────────────────────────────────────────────
# HEALTH CHECK TESTS
# ─────────────────────────────────────────────

class TestDatabaseHealth:

    def test_health_check_returns_dict(self, db_manager):
        """health_check must return a status dict"""
        with patch.object(db_manager, '_query') as mock_q:
            mock_q.return_value = [{"version": "PostgreSQL 16.0"}]
            result = db_manager.health_check()
        assert isinstance(result, dict)

    def test_health_check_has_status(self, db_manager):
        """health_check result must have status field"""
        with patch.object(db_manager, '_query') as mock_q:
            mock_q.return_value = [{"version": "PostgreSQL 16.0"}]
            result = db_manager.health_check()
        assert "status" in result

    def test_health_check_returns_healthy(self, db_manager):
        """health_check must return healthy when DB responds"""
        with patch.object(db_manager, '_query') as mock_q:
            mock_q.return_value = [{"version": "PostgreSQL 16.0"}]
            result = db_manager.health_check()
        assert result["status"] == "healthy"

    def test_health_check_returns_unhealthy_on_failure(self, db_manager):
        """health_check must return unhealthy when DB fails"""
        with patch.object(db_manager, '_query', side_effect=Exception("timeout")):
            result = db_manager.health_check()
        assert result["status"] == "unhealthy"


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def mock_open_sql():
    """Mock open() for SQL file reading"""
    from unittest.mock import mock_open
    return mock_open(read_data="CREATE TABLE IF NOT EXISTS tenants (id UUID PRIMARY KEY);")
