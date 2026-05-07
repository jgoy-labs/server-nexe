"""
Cluster 1 — config_validator._get_message conflict keyword 'key' (4 findings).

Bug: _get_message(self, key: str, **kwargs) receives TypeError when called
     self._get_message('msg_key', key='value') — 'key' is both a positional param and kwarg
     → "got multiple values for argument 'key'".

The bug occurs in the internal calls of:
  - _validate_required_keys (missing key in meta/core/etc.)
  - _validate_types_and_values (port as string, host as non-str)
  - _validate_plugins_section (temperature out of range)

Contract pin: validate() must return ValidationResult(valid=False, errors=[...]),
NOT crash with TypeError.
"""
import pytest
import toml


def test_cluster1_missing_required_key_returns_validation_error(tmp_path):
    """TDD: validate() with meta without 'version' returns ValidationResult(valid=False), NOT TypeError.

    FAILS pre-fix (TypeError at _validate_required_keys L141).
    PASSES post-fix (rename key → msg_key in _get_message signature).
    """
    from personality.module_manager.config_validator import ConfigValidator, ValidationResult

    config = {
        "meta": {"environment": "development"},  # missing 'version' and 'environment' is not sufficient
        "core": {"server": {"host": "127.0.0.1", "port": 9119}},
        "personality": {"orchestrator": {"modules_path": "plugins"}},
        "plugins": {"models": {"primary": "test"}},
        "storage": {"logging": {"level": "INFO"}},
    }
    cfg_path = tmp_path / "server.toml"
    cfg_path.write_text(toml.dumps(config))

    v = ConfigValidator()
    result = v.validate(cfg_path)

    assert isinstance(result, ValidationResult)
    assert result.valid is False
    assert len(result.errors) > 0


def test_cluster1_port_string_type_returns_validation_error(tmp_path):
    """TDD: validate() with port as string returns ValidationResult(valid=False), NOT TypeError.

    FAILS pre-fix (TypeError at _validate_types_and_values L164 — call
    _get_message('validation.type_mismatch', key='port', ...)).
    PASSES post-fix.
    """
    from personality.module_manager.config_validator import ConfigValidator, ValidationResult

    cfg_content = """\
[meta]
version = "0.9"
environment = "development"
[core.server]
host = "127.0.0.1"
port = "abc"
[personality.orchestrator]
modules_path = "plugins"
[plugins.models]
primary = "test"
[storage.logging]
level = "INFO"
"""
    cfg_path = tmp_path / "server.toml"
    cfg_path.write_text(cfg_content)

    v = ConfigValidator()
    result = v.validate(cfg_path)

    assert isinstance(result, ValidationResult)
    assert result.valid is False
    assert len(result.errors) > 0


def test_cluster1_temperature_out_of_range_returns_validation_error(tmp_path):
    """TDD: validate() with temperature=3.0 returns ValidationResult(valid=False), NOT TypeError.

    FAILS pre-fix (TypeError at _validate_plugins_section L231 — call
    _get_message('validation.value_out_of_range', key='temperature', ...)).
    PASSES post-fix.
    """
    from personality.module_manager.config_validator import ConfigValidator, ValidationResult

    config = {
        "meta": {"version": "0.9", "environment": "development"},
        "core": {"server": {"host": "127.0.0.1", "port": 9119}},
        "personality": {"orchestrator": {"modules_path": "plugins"}},
        "plugins": {"models": {"primary": "test", "temperature": 3.0}},
        "storage": {"logging": {"level": "INFO"}},
    }
    cfg_path = tmp_path / "server.toml"
    cfg_path.write_text(toml.dumps(config))

    v = ConfigValidator()
    result = v.validate(cfg_path)

    assert isinstance(result, ValidationResult)
    assert result.valid is False
    assert len(result.errors) > 0
