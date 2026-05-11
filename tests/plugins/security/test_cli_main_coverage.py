"""Tests for plugins/security/cli/main.py — coverage gaps."""
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner


runner = CliRunner()


class TestSecurityCLIInfo:
    def test_info_command(self):
        from plugins.security.cli.main import app
        mock_module = MagicMock()
        mock_module.get_info.return_value = {
            "name": "security",
            "version": "1.0.0",
            "type": "security",
            "initialized": True,
            "description": "Security module",
            "endpoints": ["/health"],
        }
        with patch("plugins.security.manifest.get_module_instance", return_value=mock_module):
            result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "security" in result.output
        assert "1.0.0" in result.output


class TestSecurityCLIHealth:
    def test_health_command_healthy(self):
        from plugins.security.cli.main import app
        with patch("plugins.security.health.get_health", return_value={
            "status": "healthy",
            "message": "All checks passed",
            "checks": [{"status": "ok", "name": "patterns", "message": "loaded"}],
        }):
            result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "healthy" in result.output

    def test_health_command_no_checks(self):
        from plugins.security.cli.main import app
        with patch("plugins.security.health.get_health", return_value={
            "status": "unknown",
        }):
            result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "unknown" in result.output


class TestSecurityCLIWorkflow:
    def test_workflow_command(self):
        from plugins.security.cli.main import app
        result = runner.invoke(app, ["workflow"])
        assert result.exit_code == 0
        assert "sanitizer_node" in result.output
