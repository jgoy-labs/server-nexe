"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/metrics/tests/test_endpoint.py
Description: Tests per Prometheus metrics endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.metrics.endpoint import metrics_router

# Bug 22: /metrics now requires X-API-Key. These tests use a fixed API key.
_TEST_KEY = "test-metrics-bug22-key"
_HEADERS = {"X-API-Key": _TEST_KEY}


@pytest.fixture(autouse=True)
def _setup_api_key(monkeypatch):
  monkeypatch.setenv("NEXE_PRIMARY_API_KEY", _TEST_KEY)
  monkeypatch.delenv("NEXE_PRIMARY_KEY_EXPIRES", raising=False)
  monkeypatch.setenv("NEXE_DEV_MODE", "false")


class TestMetricsEndpoint:
  """Tests for metrics endpoint."""

  @pytest.fixture
  def app(self):
    """Create test app with metrics router."""
    app = FastAPI()
    app.include_router(metrics_router)
    return app

  @pytest.fixture
  def client(self, app):
    """Create test client."""
    return TestClient(app)

  def test_get_metrics(self, client):
    """Test GET /metrics returns Prometheus format."""
    response = client.get("/metrics", headers=_HEADERS)
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    content = response.text
    assert "core_" in content or "python_" in content or "process_" in content

  def test_metrics_health(self, client):
    """Test GET /metrics/health."""
    response = client.get("/metrics/health", headers=_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "metrics_size_bytes" in data
    assert data["metrics_size_bytes"] > 0

  def test_metrics_json(self, client):
    """Test GET /metrics/json."""
    response = client.get("/metrics/json", headers=_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "http" in data
    assert "endpoints" in data
    assert data["endpoints"]["prometheus"] == "/metrics"

class TestMetricsContent:
  """Tests for metrics content."""

  @pytest.fixture
  def app(self):
    """Create test app."""
    app = FastAPI()
    app.include_router(metrics_router)
    return app

  @pytest.fixture
  def client(self, app):
    """Create test client."""
    return TestClient(app)


class TestMetricsHealthUnhealthy:
  """Tests for metrics_health when generate_latest fails (lines 78-80)."""

  def test_metrics_health_exception_returns_unhealthy(self):
    """Line 78-80: generate_latest raises -> unhealthy status."""
    from unittest.mock import patch
    from core.metrics.endpoint import metrics_health
    import asyncio

    with patch("core.metrics.endpoint.generate_latest", side_effect=RuntimeError("broken")):
      result = asyncio.run(metrics_health())
    assert result["status"] == "unhealthy"
    assert "broken" in result["error"]


class _RealHealthModule:
  """Minimal live module instance: health lives on the instance (like real
  plugin module instances stored on app.state.modules)."""

  def __init__(self, name, status):
    self.name = name
    self._status = status

  def get_health(self):
    return {"status": self._status}


class _FakeRequest:
  """Stand-in for fastapi.Request exposing app.state.modules."""

  def __init__(self, modules):
    class _State:
      pass

    class _App:
      pass

    self.app = _App()
    self.app.state = _State()
    self.app.state.modules = modules


class TestUpdateModuleHealth:
  """Tests for _update_module_health: reads live instances from
  app.state.modules and calls instance.get_health() (CORE2-002)."""

  def test_update_module_health_reads_live_instances(self):
    """CORE2-002 regression: health must come from the LIVE module instances
    on app.state.modules, calling instance.get_health(), and feed the gauge.

    Fails with the old code, which built a fresh empty ModuleManager()
    (list_modules() -> []) and checked module_info.get_health (ModuleInfo has
    none) -> set_module_health never called.
    """
    from unittest.mock import patch
    from core.metrics.endpoint import _update_module_health
    import asyncio

    healthy = _RealHealthModule("alpha", "healthy")
    degraded = _RealHealthModule("beta", "degraded")
    request = _FakeRequest({"alpha": healthy, "beta": degraded})

    with patch("core.metrics.endpoint.set_module_health") as mock_set:
      asyncio.run(_update_module_health(request))

    calls = {args[0]: args[1] for args, _ in mock_set.call_args_list}
    assert calls == {"alpha": "healthy", "beta": "degraded"}

  def test_update_module_health_dedupes_aliased_instances(self):
    """app.state.modules registers an instance under both module_id and .name;
    each module must be reported exactly once."""
    from unittest.mock import patch
    from core.metrics.endpoint import _update_module_health
    import asyncio

    inst = _RealHealthModule("web_ui_module", "healthy")
    # Same instance under two keys (module_id + name), as lifespan does.
    request = _FakeRequest({"web_ui": inst, "web_ui_module": inst})

    with patch("core.metrics.endpoint.set_module_health") as mock_set:
      asyncio.run(_update_module_health(request))

    assert mock_set.call_count == 1
    assert mock_set.call_args[0] == ("web_ui_module", "healthy")

  def test_update_module_health_get_health_exception(self):
    """get_health raises -> module marked unhealthy."""
    from unittest.mock import patch
    from core.metrics.endpoint import _update_module_health
    import asyncio

    class _Broken:
      name = "broken_mod"

      def get_health(self):
        raise RuntimeError("fail")

    request = _FakeRequest({"broken_mod": _Broken()})

    with patch("core.metrics.endpoint.set_module_health") as mock_set:
      asyncio.run(_update_module_health(request))
    mock_set.assert_called_with("broken_mod", "unhealthy")

  def test_update_module_health_skips_instances_without_get_health(self):
    """Instances lacking get_health (e.g. ModuleInfo dataclass) are skipped,
    not crashed on."""
    from unittest.mock import patch
    from core.metrics.endpoint import _update_module_health
    import asyncio

    class _NoHealth:
      name = "plain"

    request = _FakeRequest({"plain": _NoHealth()})

    with patch("core.metrics.endpoint.set_module_health") as mock_set:
      asyncio.run(_update_module_health(request))
    mock_set.assert_not_called()

  def test_update_module_health_no_state_modules(self):
    """Missing app.state.modules is handled gracefully (no raise)."""
    from core.metrics.endpoint import _update_module_health
    import asyncio

    class _State:
      pass

    class _App:
      pass

    class _Req:
      pass

    req = _Req()
    req.app = _App()
    req.app.state = _State()  # no .modules attribute

    # Should not raise.
    asyncio.run(_update_module_health(req))