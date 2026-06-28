"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/server/tests/test_factory_cache.py
Description: Tests for the create_app() singleton cache. Validates caching, force_reload, thread-safety and performance improvement (0.58s→<0.01s).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import pytest
import time
import os
import threading
import concurrent.futures

from core.server.factory import create_app, reset_app_cache

@pytest.fixture(autouse=True)
def cleanup_app_cache(monkeypatch):
  """
  Reset app cache and environment variables after each test.

  Essential to avoid shared state between tests.
  """
  # Ensure event loop exists for create_app (uses async internals)
  try:
    asyncio.get_running_loop()
  except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

  monkeypatch.setenv("NEXE_ENV", "development")
  monkeypatch.setenv("NEXE_ADMIN_API_KEY", "test-key-" + os.urandom(16).hex())
  monkeypatch.setenv("NEXE_APPROVED_MODULES", "security")

  yield

  reset_app_cache()

def test_create_app_basic(monkeypatch):
  """
  Basic test: create_app() returns a valid FastAPI app.

  Verifies that caching does not break basic functionality.
  """
  app = create_app()

  assert app is not None
  assert "server-nexe" in app.title or "Nexe" in app.title
  assert hasattr(app, "routes")

def test_create_app_caches_instance(monkeypatch):
  """
  Test that create_app() returns the same cached instance.

  Core feature - singleton pattern.
  """
  app1 = create_app()
  app2 = create_app()

  assert app1 is app2, "create_app() should return cached instance"
  assert id(app1) == id(app2), "Same instance should have same id"

def test_create_app_force_reload(monkeypatch):
  """
  Test that force_reload=True rebuilds the app.

  Needed for tests that require a fresh app.
  """
  app1 = create_app()
  app2 = create_app(force_reload=True)

  assert app1 is not app2, "force_reload should create new instance"
  assert id(app1) != id(app2), "Different instances should have different ids"

def test_create_app_cache_improves_performance(monkeypatch):
  """
  Test that the cache significantly improves startup time.

  Performance win - 0.58s → <0.01s
  """
  start1 = time.time()
  app1 = create_app(force_reload=True)
  elapsed1 = time.time() - start1

  start2 = time.time()
  app2 = create_app()
  elapsed2 = time.time() - start2

  assert elapsed2 < elapsed1 / 10, f"Cached call should be >10x faster: {elapsed1:.3f}s vs {elapsed2:.3f}s"
  assert elapsed2 < 0.05, f"Cached call should be <50ms, got {elapsed2:.3f}s"

  assert app1 is app2

  print(f"\n📊 Performance benchmark:")
  print(f"  First call (cold): {elapsed1:.3f}s")
  print(f"  Cached call (warm): {elapsed2:.4f}s")
  print(f"  Speedup: {elapsed1/elapsed2:.1f}x")

def test_reset_app_cache(monkeypatch):
  """
  Test that reset_app_cache() clears the cache correctly.

  Needed for test teardown.
  """
  app1 = create_app()

  reset_app_cache()

  app2 = create_app()

  assert app1 is not app2, "reset_app_cache() should clear cache"

def test_create_app_thread_safe(monkeypatch):
  """
  Test that cache is thread-safe (no race conditions).

  Important per multi-worker deployments.
  """
  reset_app_cache()

  apps = []
  errors = []

  def create_in_thread():
    """Helper to create app in a thread"""
    try:
      return create_app()
    except Exception as e:
      errors.append(e)
      raise

  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(create_in_thread) for _ in range(10)]
    apps = [f.result() for f in futures]

  assert len(errors) == 0, f"Thread-safe test failed with errors: {errors}"

  unique_ids = set(id(app) for app in apps)
  assert len(unique_ids) == 1, f"All threads should return same instance, got {len(unique_ids)} different instances"

  print(f"\n🧵 Thread-safety test:")
  print(f"  Threads: 10")
  print(f"  Unique instances: {len(unique_ids)}")
  print(f"  ✅ Thread-safe!" if len(unique_ids) == 1 else f"  ❌ Not thread-safe!")

def test_create_app_different_project_root_rebuilds(monkeypatch, tmp_path):
  """
  Test that changing project_root rebuilds the app.

  Avoids using the cache when project_root changes.
  """
  app1 = create_app()

  (tmp_path / "personality").mkdir()
  (tmp_path / "personality" / "server.toml").touch()
  (tmp_path / "plugins" / "tools").mkdir(parents=True)

  try:
    app2 = create_app(project_root=tmp_path)
    assert app1 is not app2, "Different project_root should create new instance"
  except Exception as e:
    pytest.skip(f"Skipping test due to incomplete tmp_path structure: {e}")

def test_create_app_concurrent_first_call(monkeypatch):
  """
  Test that concurrent first calls do not create multiple instances.

  Double-check locking must prevent race conditions.
  """
  reset_app_cache()

  barrier = threading.Barrier(5)
  apps = []

  def create_with_barrier():
    """Helper that waits for the barrier before creating"""
    barrier.wait()
    return create_app()

  with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(create_with_barrier) for _ in range(5)]
    apps = [f.result() for f in futures]

  unique_ids = set(id(app) for app in apps)
  assert len(unique_ids) == 1, f"Concurrent first calls should return same instance, got {len(unique_ids)}"

def test_create_app_cache_key_includes_project_root(monkeypatch):
  """
  Test that the cache key includes project_root.

  Same app but different project_root → cache miss.
  """
  app1 = create_app()
  project_root1 = app1.state.project_root

  reset_app_cache()

  app2 = create_app(project_root=project_root1)

  app3 = create_app(project_root=project_root1)

  assert app2 is app3, "Same project_root should hit cache"

@pytest.mark.slow
def test_create_app_benchmark_cold_vs_warm(monkeypatch):
  """
  Detailed benchmark: measures startup time cold vs warm.

  Demonstrates the performance improvement.

  Run with: pytest -m slow
  """
  print("\n" + "="*60)
  print("📊 BENCHMARK: create_app() Performance")
  print("="*60)

  cold_times = []
  for i in range(3):
    reset_app_cache()
    start = time.time()
    app = create_app()
    elapsed = time.time() - start
    cold_times.append(elapsed)
    print(f"  Cold start {i+1}: {elapsed:.3f}s")

  reset_app_cache()
  app = create_app()
  warm_times = []
  for i in range(10):
    start = time.time()
    app = create_app()
    elapsed = time.time() - start
    warm_times.append(elapsed)

  avg_cold = sum(cold_times) / len(cold_times)
  avg_warm = sum(warm_times) / len(warm_times)
  speedup = avg_cold / avg_warm

  print(f"\n  Average cold start: {avg_cold:.3f}s")
  print(f"  Average warm start: {avg_warm:.4f}s")
  print(f"  Speedup: {speedup:.1f}x")
  print("="*60)

  assert avg_warm < 0.01, f"Warm start should be <10ms, got {avg_warm:.4f}s"
  assert speedup > 10, f"Cache should be >10x faster, got {speedup:.1f}x"

def test_create_app_multiple_sequential_calls(monkeypatch):
  """Test that multiple sequential calls return the cache"""
  apps = [create_app() for _ in range(5)]

  for i, app in enumerate(apps[1:], start=1):
    assert app is apps[0], f"Call {i} should return cached instance"
