"""One ONNX session per (model, cache_dir, threads), not one per call site.

Each fastembed TextEmbedding builds its own ONNX InferenceSession holding its
own copy of the weights (~1.4 GB for the multilingual mpnet model in FP32).
MemoryAPI and the ingestion pipeline each built one, so a low-RAM machine paid
for the embedder twice before the LLM asked for anything.
"""

from unittest.mock import patch

import pytest

from memory.embeddings import shared


class _FakeTextEmbedding:
    instances = 0

    def __init__(self, model_name, **kwargs):
        _FakeTextEmbedding.instances += 1
        self.model_name = model_name
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    shared.reset_shared_embedders()
    _FakeTextEmbedding.instances = 0
    monkeypatch.delenv("NEXE_SHARED_EMBEDDER", raising=False)
    fake_module = type("M", (), {"TextEmbedding": _FakeTextEmbedding})
    with patch.dict("sys.modules", {"fastembed": fake_module}):
        yield
    shared.reset_shared_embedders()


def test_same_params_reuse_one_instance():
    first = shared.get_text_embedding("mpnet")
    second = shared.get_text_embedding("mpnet")
    assert first is second
    assert _FakeTextEmbedding.instances == 1


def test_different_thread_counts_are_not_shared():
    """threads= changes the ORT pool; conflating them would silently reconfigure."""
    shared.get_text_embedding("mpnet", threads=None)
    shared.get_text_embedding("mpnet", threads=6)
    assert _FakeTextEmbedding.instances == 2


def test_different_models_are_not_shared():
    shared.get_text_embedding("mpnet")
    shared.get_text_embedding("other-model")
    assert _FakeTextEmbedding.instances == 2


def test_cache_dir_is_always_passed():
    """Anti-regression for the existing paths gate: never rely on the default."""
    instance = shared.get_text_embedding("mpnet")
    assert "cache_dir" in instance.kwargs and instance.kwargs["cache_dir"]


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_escape_hatch_restores_per_call_instances(monkeypatch, value):
    monkeypatch.setenv("NEXE_SHARED_EMBEDDER", value)
    first = shared.get_text_embedding("mpnet")
    second = shared.get_text_embedding("mpnet")
    assert first is not second
    assert _FakeTextEmbedding.instances == 2


def test_failed_construction_is_not_cached():
    """A model missing at boot must not poison the cache for a later retry."""
    class _Boom(_FakeTextEmbedding):
        def __init__(self, *a, **kw):
            raise RuntimeError("model not downloaded yet")

    boom_module = type("M", (), {"TextEmbedding": _Boom})
    with patch.dict("sys.modules", {"fastembed": boom_module}):
        with pytest.raises(RuntimeError):
            shared.get_text_embedding("mpnet")
    # fastembed is the working fake again (outer fixture): the retry succeeds.
    assert shared.get_text_embedding("mpnet") is not None


def test_simple_embedder_shares_the_same_session():
    """SimpleEmbedder (DreamingCycle) must not build a session of its own.

    It runs on every boot where onboarding is complete, so its private ONNX
    session cost ~925 MB on top of the shared one — about 40% of the saving.
    """
    from memory.embeddings.simple_embedder import SimpleEmbedder, get_embedder

    SimpleEmbedder._instances.clear()
    try:
        embedder = get_embedder("mpnet")
        assert embedder.model is shared.get_text_embedding("mpnet")
        assert _FakeTextEmbedding.instances == 1, "a second ONNX session was built"
    finally:
        SimpleEmbedder._instances.clear()


def test_concurrent_first_use_builds_exactly_one(monkeypatch):
    """The double-checked lock must hold under a real startup race."""
    import threading

    barrier = threading.Barrier(8)
    results = []

    def _worker():
        barrier.wait()
        results.append(shared.get_text_embedding("mpnet"))

    workers = [threading.Thread(target=_worker) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    assert _FakeTextEmbedding.instances == 1, "the lock let a duplicate session through"
    assert len(results) == 8 and all(r is results[0] for r in results)
