"""
Tests for uncovered lines in personality/data/models.py.
Targets: 28 lines missing
"""
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock
from personality.data.models import (
    ModuleInfo, ModuleState, SystemStatus, HealthStatus,
    SystemEvent, HealthCheck, SystemMetrics, EndpointInfo,
    ModuleRegistration, ConfigSection, ValidationResult,
    detect_dependency_cycles, calculate_module_uptime,
    get_module_state_display_name, create_module_info,
    create_system_event, set_i18n_manager, _t,
)


class TestTranslationHelper:

    def test_t_with_i18n_manager(self):
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "translated"
        set_i18n_manager(mock_i18n)
        result = _t("some.key")
        assert result == "translated"
        set_i18n_manager(None)  # cleanup

    def test_t_without_i18n_known_key(self):
        set_i18n_manager(None)
        result = _t("core_models.module_states.running")
        assert result == "Running"

    def test_t_unknown_key(self):
        set_i18n_manager(None)
        result = _t("unknown.key.here")
        assert result == "unknown.key.here"

    def test_t_format_error(self):
        """Lines 72-74: format fails, returns raw message."""
        set_i18n_manager(None)
        result = _t("core_models.module_states.running", missing_key="val")
        # Returns the message without formatting
        assert result == "Running"


class TestDetectDependencyCycles:

    def test_no_cycle(self):
        modules = {
            "a": ModuleInfo(name="a", path=Path("."), manifest_path=Path("."), dependencies=["b"]),
            "b": ModuleInfo(name="b", path=Path("."), manifest_path=Path("."), dependencies=[]),
        }
        assert detect_dependency_cycles(modules) is None

    def test_simple_cycle(self):
        modules = {
            "a": ModuleInfo(name="a", path=Path("."), manifest_path=Path("."), dependencies=["b"]),
            "b": ModuleInfo(name="b", path=Path("."), manifest_path=Path("."), dependencies=["a"]),
        }
        result = detect_dependency_cycles(modules)
        assert result is not None
        assert "a" in result and "b" in result

    def test_self_cycle(self):
        modules = {
            "a": ModuleInfo(name="a", path=Path("."), manifest_path=Path("."), dependencies=["a"]),
        }
        result = detect_dependency_cycles(modules)
        assert result is not None

    def test_no_modules(self):
        assert detect_dependency_cycles({}) is None

    def test_dependency_to_missing_module(self):
        """Line 239-240: dependency references non-existent module."""
        modules = {
            "a": ModuleInfo(name="a", path=Path("."), manifest_path=Path("."), dependencies=["missing"]),
        }
        result = detect_dependency_cycles(modules)
        assert result is None


class TestCalculateModuleUptime:

    def test_running_module_has_uptime(self):
        module = ModuleInfo(
            name="test", path=Path("."), manifest_path=Path("."),
            state=ModuleState.RUNNING,
            start_time=datetime.now(timezone.utc)
        )
        result = calculate_module_uptime(module)
        assert result is not None
        assert result >= 0

    def test_stopped_module_returns_none(self):
        module = ModuleInfo(
            name="test", path=Path("."), manifest_path=Path("."),
            state=ModuleState.STOPPED,
            start_time=datetime.now(timezone.utc)
        )
        result = calculate_module_uptime(module)
        assert result is None

    def test_no_start_time_returns_none(self):
        module = ModuleInfo(
            name="test", path=Path("."), manifest_path=Path("."),
            state=ModuleState.RUNNING,
            start_time=None
        )
        result = calculate_module_uptime(module)
        assert result is None


class TestGetModuleStateDisplayName:

    def test_with_i18n_manager(self):
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Executant"
        result = get_module_state_display_name(ModuleState.RUNNING, mock_i18n)
        assert result == "Executant"

    def test_without_i18n_manager(self):
        result = get_module_state_display_name(ModuleState.RUNNING)
        assert result == "Running"

    def test_all_states_have_display_name(self):
        for state in ModuleState:
            result = get_module_state_display_name(state)
            assert isinstance(result, str)
            assert len(result) > 0


class TestCreateModuleInfo:

    def test_create_with_string_path(self):
        mi = create_module_info("test", "/fake/path")
        assert mi.name == "test"
        assert mi.path == Path("/fake/path")

    def test_create_with_path_object(self):
        mi = create_module_info("test", Path("/fake"))
        assert mi.path == Path("/fake")

    def test_create_with_custom_manifest_path(self):
        mi = create_module_info("test", "/fake", manifest_path=Path("/custom/manifest.toml"))
        assert mi.manifest_path == Path("/custom/manifest.toml")

    def test_create_default_manifest_path(self):
        mi = create_module_info("test", "/fake")
        assert "manifest.toml" in str(mi.manifest_path)


class TestCreateSystemEvent:

    def test_create_with_defaults(self):
        event = create_system_event("src", "type")
        assert event.source == "src"
        assert event.event_type == "type"
        assert event.level == "info"

    def test_create_with_level(self):
        event = create_system_event("src", "type", level="error")
        assert event.level == "error"

    def test_create_with_details(self):
        event = create_system_event("src", "type", key="value", count=5)
        assert event.details["key"] == "value"
        assert event.details["count"] == 5


class TestDataclasses:

    def test_health_check_defaults(self):
        hc = HealthCheck(
            name="test", status=HealthStatus.HEALTHY, message="ok"
        )
        assert hc.timestamp is not None
        assert hc.duration_ms is None

    def test_system_metrics(self):
        sm = SystemMetrics(
            timestamp=datetime.now(timezone.utc),
            total_modules=5, running_modules=3,
            total_memory_mb=100.0, average_cpu_usage=25.0,
            average_load_time_ms=50.0, total_api_calls=100,
            modules_with_errors=1, states_breakdown={"running": 3},
            uptime_seconds=1000.0
        )
        assert sm.total_modules == 5

    def test_endpoint_info(self):
        ei = EndpointInfo(path="/test", method="GET", function="handler", module_name="mod")
        assert ei.path == "/test"

    def test_module_registration(self):
        mr = ModuleRegistration(
            name="test", instance=None, manifest={},
            registration_time=datetime.now(timezone.utc)
        )
        assert mr.name == "test"

    def test_config_section(self):
        cs = ConfigSection(name="core", required=True, description="Core config")
        assert cs.required is True

    def test_validation_result(self):
        vr = ValidationResult(valid=True)
        assert vr.errors == []
        assert vr.warnings == []
