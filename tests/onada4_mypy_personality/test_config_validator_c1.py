"""
Cluster 1 — config_validator._get_message conflict keyword 'key' (4 findings).

Bug: _get_message(self, key: str, **kwargs) rep TypeError quan es crida
     self._get_message('msg_key', key='value') — 'key' és param posicional i kwarg
     alhora → "got multiple values for argument 'key'".

El bug ocorre a les crides internes de:
  - _validate_required_keys (clau faltant a meta/core/etc.)
  - _validate_types_and_values (port com a string, host com a non-str)
  - _validate_plugins_section (temperature fora de rang)

Contract pin: validate() ha de retornar ValidationResult(valid=False, errors=[...]),
NO crashar amb TypeError.
"""
import pytest
import toml


def test_cluster1_missing_required_key_returns_validation_error(tmp_path):
    """TDD: validate() amb meta sense 'version' retorna ValidationResult(valid=False), NO TypeError.

    FALLA pre-fix (TypeError a _validate_required_keys L141).
    PASSA post-fix (rename key → msg_key en signatura _get_message).
    """
    from personality.module_manager.config_validator import ConfigValidator, ValidationResult

    config = {
        "meta": {"environment": "development"},  # manquen 'version' i 'environment' no és suficient
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
    """TDD: validate() amb port com a string retorna ValidationResult(valid=False), NO TypeError.

    FALLA pre-fix (TypeError a _validate_types_and_values L164 — crida
    _get_message('validation.type_mismatch', key='port', ...)).
    PASSA post-fix.
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
    """TDD: validate() amb temperature=3.0 retorna ValidationResult(valid=False), NO TypeError.

    FALLA pre-fix (TypeError a _validate_plugins_section L231 — crida
    _get_message('validation.value_out_of_range', key='temperature', ...)).
    PASSA post-fix.
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
