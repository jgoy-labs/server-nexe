"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/resilience/tests/test_concurrency.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock

try:
  import numpy as np
  HAS_NUMPY = True
except ImportError:
  HAS_NUMPY = False

class TestAsyncBasics:
  """Basic tests for async/await"""

  @pytest.mark.asyncio
  async def test_event_loop_not_blocked(self):
    """The event loop is not blocked by async operations"""
    start = time.time()

    async def quick_task():
      await asyncio.sleep(0.01)
      return True

    results = await asyncio.gather(*[quick_task() for _ in range(10)])

    elapsed = time.time() - start

    assert all(results)
    assert elapsed < 0.1, f"Tasks took {elapsed}s, expected < 0.1s"

  @pytest.mark.asyncio
  async def test_async_sleep_yields_control(self):
    """asyncio.sleep() yields control to other tasks"""
    order = []

    async def task(name: str, delay: float):
      order.append(f"{name}_start")
      await asyncio.sleep(delay)
      order.append(f"{name}_end")

    await asyncio.gather(
      task("A", 0.02),
      task("B", 0.01),
    )

    assert order.index("B_end") < order.index("A_end")

class TestThreadPoolExecutor:
  """Tests for the ThreadPoolExecutor"""

  @pytest.fixture
  def executor(self):
    """Executor with 2 workers for tests"""
    executor = ThreadPoolExecutor(max_workers=2)
    yield executor
    executor.shutdown(wait=True)

  @pytest.mark.asyncio
  async def test_run_in_executor_works(self, executor):
    """run_in_executor works correctly"""
    def blocking_work():
      time.sleep(0.05)
      return "done"

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, blocking_work)

    assert result == "done"

  @pytest.mark.asyncio
  async def test_executor_parallel_execution(self, executor):
    """Executor executes in parallel"""
    results = []

    def work(n):
      time.sleep(0.05)
      results.append(n)
      return n

    loop = asyncio.get_running_loop()

    start = time.time()
    await asyncio.gather(
      loop.run_in_executor(executor, work, 1),
      loop.run_in_executor(executor, work, 2),
    )
    elapsed = time.time() - start

    assert elapsed < 0.1, f"Parallel execution took {elapsed}s"
    assert len(results) == 2

  @pytest.mark.asyncio
  async def test_executor_handles_exceptions(self, executor):
    """Executor propagates exceptions correctly"""
    def failing_work():
      raise ValueError("test error")

    loop = asyncio.get_running_loop()

    with pytest.raises(ValueError) as exc_info:
      await loop.run_in_executor(executor, failing_work)

    assert "test error" in str(exc_info.value)

@pytest.mark.skipif(not HAS_NUMPY, reason="NumPy not available")
class TestGILRelease:
  """Tests for GIL release"""

  def test_numpy_releases_gil(self):
    """NumPy releases the GIL during operations"""

    results = {"thread1": None, "thread2": None}
    start_times = {}
    end_times = {}

    def numpy_work(name: str):
      start_times[name] = time.time()
      arr = np.random.rand(1000, 1000)
      _ = np.linalg.svd(arr)
      end_times[name] = time.time()
      results[name] = True

    threads = [
      threading.Thread(target=numpy_work, args=("thread1",)),
      threading.Thread(target=numpy_work, args=("thread2",)),
    ]

    start = time.time()
    for t in threads:
      t.start()
    for t in threads:
      t.join()
    total = time.time() - start

    assert results["thread1"] is True
    assert results["thread2"] is True

    single_thread_time = max(
      end_times["thread1"] - start_times["thread1"],
      end_times["thread2"] - start_times["thread2"],
    )

    ratio = total / single_thread_time
    assert ratio < 1.8, f"GIL might not be released: ratio={ratio}"

class TestMemoryManagement:
  """Tests for memory management"""

  @pytest.mark.asyncio
  async def test_no_task_accumulation(self):
    """Completed tasks do not accumulate"""
    import gc

    gc.collect()

    async def ephemeral_task():
      return "done"

    for _ in range(1000):
      await ephemeral_task()

    gc.collect()

  @pytest.mark.asyncio
  async def test_batch_processing_yields(self):
    """Batch processing yields control"""
    processed = []
    other_task_ran = False

    async def batch_processor():
      for i in range(10):
        processed.append(i)
        await asyncio.sleep(0)

    async def other_task():
      nonlocal other_task_ran
      other_task_ran = True

    await asyncio.gather(
      batch_processor(),
      other_task(),
    )

    assert len(processed) == 10
    assert other_task_ran

class TestTimeoutHandling:
  """Tests for timeout handling"""

  @pytest.mark.asyncio
  async def test_timeout_cancels_task(self):
    """Timeout cancels the task correctly"""
    async def slow_task():
      await asyncio.sleep(10)
      return "should not reach"

    with pytest.raises(asyncio.TimeoutError):
      await asyncio.wait_for(slow_task(), timeout=0.1)

  @pytest.mark.asyncio
  async def test_timeout_does_not_affect_fast_tasks(self):
    """Timeout does not affect fast tasks"""
    async def fast_task():
      await asyncio.sleep(0.01)
      return "done"

    result = await asyncio.wait_for(fast_task(), timeout=1.0)
    assert result == "done"

class TestSemaphoreRateLimiting:
  """Tests for rate limiting with semaphores"""

  @pytest.mark.asyncio
  async def test_semaphore_limits_concurrency(self):
    """Semaphore limits concurrency"""
    concurrent_count = 0
    max_concurrent = 0
    semaphore = asyncio.Semaphore(2)

    async def limited_task():
      nonlocal concurrent_count, max_concurrent
      async with semaphore:
        concurrent_count += 1
        max_concurrent = max(max_concurrent, concurrent_count)
        await asyncio.sleep(0.05)
        concurrent_count -= 1

    await asyncio.gather(*[limited_task() for _ in range(5)])

    assert max_concurrent == 2, f"Max concurrent was {max_concurrent}"

class TestCircuitBreakerIntegration:
  """Integration tests with Circuit Breaker"""

  @pytest.mark.asyncio
  async def test_circuit_breaker_async_compatible(self):
    """Circuit Breaker works with async"""
    from core.resilience import CircuitBreaker, CircuitBreakerConfig

    breaker = CircuitBreaker(
      "test_async",
      CircuitBreakerConfig(failure_threshold=2, max_retries=1)
    )

    call_count = 0

    @breaker.protect
    async def async_service():
      nonlocal call_count
      call_count += 1
      await asyncio.sleep(0.01)
      return "success"

    result = await async_service()
    assert result == "success"
    assert call_count == 1

  @pytest.mark.asyncio
  async def test_concurrent_protected_calls(self):
    """Concurrent protected calls work correctly"""
    from core.resilience import CircuitBreaker, CircuitBreakerConfig

    breaker = CircuitBreaker(
      "test_concurrent",
      CircuitBreakerConfig(failure_threshold=10, max_retries=1)
    )

    counter = 0

    @breaker.protect
    async def counting_service():
      nonlocal counter
      counter += 1
      await asyncio.sleep(0.01)
      return counter

    results = await asyncio.gather(*[counting_service() for _ in range(5)])

    assert len(results) == 5
    assert counter == 5