"""
Tests per core/bootstrap_tokens.py — BootstrapTokenManager
"""
import pytest
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone


class TestBootstrapTokenManagerSingleton:
    def test_singleton_pattern(self):
        from core.bootstrap_tokens import BootstrapTokenManager
        m1 = BootstrapTokenManager()
        m2 = BootstrapTokenManager()
        assert m1 is m2

    def test_initialization(self, tmp_path):
        from core.bootstrap_tokens import BootstrapTokenManager
        # Crear instància nova per test
        manager = BootstrapTokenManager()
        # Forçar reinicialització per al tmp_path del test
        manager._initialized = False
        manager.initialize_on_startup(tmp_path)
        assert manager._initialized is True
        db_file = tmp_path / "storage" / "system_core.db"
        assert db_file.exists()

    def test_double_initialization_noop(self, tmp_path):
        from core.bootstrap_tokens import BootstrapTokenManager
        manager = BootstrapTokenManager()
        manager._initialized = False
        manager.initialize_on_startup(tmp_path)
        # Cridar de nou no ha de fallar
        manager.initialize_on_startup(tmp_path)
        assert manager._initialized is True


class TestSessionTokens:
    def setup_method(self):
        """Reinicialitzar manager per cada test"""
        from core.bootstrap_tokens import BootstrapTokenManager
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.manager = BootstrapTokenManager()
        self.manager._initialized = False
        self.manager.initialize_on_startup(self.tmp)

    def test_create_session_token(self):
        token = self.manager.create_session_token(ttl_seconds=900)
        assert token is not None
        assert len(token) > 20

    def test_validate_valid_token(self):
        token = self.manager.create_session_token(ttl_seconds=900)
        assert self.manager.validate_session_token(token) is True

    def test_validate_invalid_token(self):
        assert self.manager.validate_session_token("token_inexistent") is False

    def test_validate_expired_token(self):
        """Token amb TTL de 0 o negatiu → expirat"""
        token = self.manager.create_session_token(ttl_seconds=-1)
        # El token ha expirat immediatament
        assert self.manager.validate_session_token(token) is False

    def test_invalidate_token(self):
        token = self.manager.create_session_token(ttl_seconds=900)
        self.manager.invalidate_token(token)
        assert self.manager.validate_session_token(token) is False

    def test_invalidate_nonexistent_token_noop(self):
        # No ha de llençar excepcions
        self.manager.invalidate_token("token_que_no_existeix")

    def test_create_multiple_tokens(self):
        token1 = self.manager.create_session_token()
        token2 = self.manager.create_session_token()
        assert token1 != token2


class TestBootstrapMasterToken:
    def setup_method(self):
        from core.bootstrap_tokens import BootstrapTokenManager
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.manager = BootstrapTokenManager()
        self.manager._initialized = False
        self.manager.initialize_on_startup(self.tmp)

    def test_set_and_get_bootstrap_token(self):
        self.manager.set_bootstrap_token("test-token-123", ttl_minutes=30)
        info = self.manager.get_bootstrap_token()
        assert info is not None
        assert info["token"] == "test-token-123"
        assert info["used"] is False

    def test_get_bootstrap_token_not_set(self):
        result = self.manager.get_bootstrap_token()
        assert result is None

    def test_validate_master_bootstrap_valid(self):
        self.manager.set_bootstrap_token("secret-token", ttl_minutes=30)
        result = self.manager.validate_master_bootstrap("secret-token")
        assert result is True

    def test_validate_master_bootstrap_wrong_token(self):
        self.manager.set_bootstrap_token("secret-token", ttl_minutes=30)
        result = self.manager.validate_master_bootstrap("wrong-token")
        assert result is False

    def test_validate_master_bootstrap_already_used(self):
        """Token de bootstrap ja usat → refusar"""
        self.manager.set_bootstrap_token("secret-token", ttl_minutes=30)
        result1 = self.manager.validate_master_bootstrap("secret-token")
        assert result1 is True
        # Segon intent → refusar
        result2 = self.manager.validate_master_bootstrap("secret-token")
        assert result2 is False

    def test_validate_master_bootstrap_no_token(self):
        result = self.manager.validate_master_bootstrap("qualsevol")
        assert result is False

    def test_set_bootstrap_token_resets_used_status(self):
        self.manager.set_bootstrap_token("token-v1", ttl_minutes=30)
        self.manager.validate_master_bootstrap("token-v1")  # usar
        # Establir token nou → reset de l'estat "used"
        self.manager.set_bootstrap_token("token-v2", ttl_minutes=30)
        info = self.manager.get_bootstrap_token()
        assert info["used"] is False


class TestBootstrapRateLimit:
    def setup_method(self):
        from core.bootstrap_tokens import BootstrapTokenManager
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.manager = BootstrapTokenManager()
        self.manager._initialized = False
        self.manager.initialize_on_startup(self.tmp)

    def test_first_attempt_allowed(self):
        result = self.manager.check_bootstrap_rate_limit("192.168.1.1")
        assert result == "ok"

    def test_ip_limit_exceeded(self):
        ip = "192.168.1.2"
        # ip_limit=3 per defecte
        self.manager.check_bootstrap_rate_limit(ip)
        self.manager.check_bootstrap_rate_limit(ip)
        self.manager.check_bootstrap_rate_limit(ip)
        result = self.manager.check_bootstrap_rate_limit(ip)
        assert result == "ip"

    def test_global_limit_exceeded(self):
        # global_limit=10 per defecte
        for i in range(10):
            self.manager.check_bootstrap_rate_limit(f"10.0.0.{i + 1}")
        result = self.manager.check_bootstrap_rate_limit("10.0.1.1")
        assert result == "global"

    def test_window_resets_after_expiry(self):
        ip = "192.168.1.3"
        # Usar window_seconds molt petit per simular expiració
        for _ in range(3):
            self.manager.check_bootstrap_rate_limit(ip, window_seconds=0)
        # Amb window=0, tots els intents expiren immediatament
        result = self.manager.check_bootstrap_rate_limit(ip, window_seconds=0)
        assert result == "ok"


class TestModuleLevelFunctions:
    def test_initialize_tokens_function(self, tmp_path):
        from core.bootstrap_tokens import initialize_tokens
        initialize_tokens(tmp_path)
        # No ha de llençar excepcions

    def test_set_get_bootstrap_token_functions(self, tmp_path):
        from core.bootstrap_tokens import (
            initialize_tokens, set_bootstrap_token, get_bootstrap_token
        )
        initialize_tokens(tmp_path)
        set_bootstrap_token("test-123", ttl_minutes=10)
        info = get_bootstrap_token()
        assert info is not None

    def test_validate_master_bootstrap_function(self, tmp_path):
        from core.bootstrap_tokens import (
            initialize_tokens, set_bootstrap_token, validate_master_bootstrap
        )
        initialize_tokens(tmp_path)
        set_bootstrap_token("my-token", ttl_minutes=10)
        assert validate_master_bootstrap("my-token") is True

    def test_check_rate_limit_function(self, tmp_path):
        from core.bootstrap_tokens import initialize_tokens, check_bootstrap_rate_limit
        initialize_tokens(tmp_path)
        result = check_bootstrap_rate_limit("1.2.3.4")
        assert result in ("ok", "global", "ip")

    def test_create_validate_invalidate_functions(self, tmp_path):
        from core.bootstrap_tokens import (
            initialize_tokens, create_session_token,
            validate_session_token, invalidate_token
        )
        initialize_tokens(tmp_path)
        token = create_session_token(ttl_seconds=900)
        assert validate_session_token(token) is True
        invalidate_token(token)
        assert validate_session_token(token) is False
