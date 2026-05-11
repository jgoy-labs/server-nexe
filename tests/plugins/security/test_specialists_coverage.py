"""Tests for plugins/security/specialists/ — stub coverage."""
import pytest


class TestSecurityPluginSpecialist:
    def test_raises_not_implemented(self):
        from plugins.security.specialists.plugin_specialist import SecurityPluginSpecialist
        with pytest.raises(NotImplementedError, match="Stub"):
            SecurityPluginSpecialist().get_health_report()


class TestSecurityTestSpecialist:
    def test_raises_not_implemented(self):
        from plugins.security.specialists.test_specialist import SecurityTestSpecialist
        with pytest.raises(NotImplementedError, match="Stub"):
            SecurityTestSpecialist().get_test_report()


class TestSecurityTrasherSpecialist:
    def test_raises_not_implemented(self):
        from plugins.security.specialists.trasher_specialist import SecurityTrasherSpecialist
        with pytest.raises(NotImplementedError, match="Stub"):
            SecurityTrasherSpecialist().get_storage_report()
