import pytest
from nexus.api.main import _validate_production_security


class TestProductionSecurity:
    def test_weak_secret_key_rejected(self, monkeypatch):
        """弱 SECRET_KEY（短于32字符）触发 RuntimeError"""
        from nexus import config
        monkeypatch.setattr(config.settings, "SECRET_KEY", "short")
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(config.settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(config.settings, "DEV_API_KEY", None)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            _validate_production_security()

    def test_default_secret_key_rejected(self, monkeypatch):
        """默认 SECRET_KEY 触发 RuntimeError"""
        from nexus import config
        monkeypatch.setattr(config.settings, "SECRET_KEY", "nexus-dev-secret-not-for-production")
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(config.settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(config.settings, "DEV_API_KEY", None)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            _validate_production_security()

    def test_sqlite_in_production_rejected(self, monkeypatch):
        """生产环境使用 SQLite 触发 RuntimeError"""
        from nexus import config
        monkeypatch.setattr(config.settings, "SECRET_KEY", "a" * 32)
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(config.settings, "DATABASE_URL", "sqlite:///test.db")
        monkeypatch.setattr(config.settings, "DEV_API_KEY", None)
        with pytest.raises(RuntimeError, match="SQLite"):
            _validate_production_security()

    def test_dev_api_key_in_production_rejected(self, monkeypatch):
        """生产环境 DEV_API_KEY 触发 RuntimeError"""
        from nexus import config
        monkeypatch.setattr(config.settings, "SECRET_KEY", "a" * 32)
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(config.settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(config.settings, "DEV_API_KEY", "dev-key-123")
        with pytest.raises(RuntimeError, match="DEV_API_KEY"):
            _validate_production_security()

    def test_valid_production_config_passes(self, monkeypatch):
        """有效生产配置应通过校验"""
        from nexus import config
        monkeypatch.setattr(config.settings, "SECRET_KEY", "a" * 32)
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(config.settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(config.settings, "DEV_API_KEY", None)
        _validate_production_security()  # 不应抛出异常
