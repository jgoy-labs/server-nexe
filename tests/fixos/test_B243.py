"""
Test fix B243: reset_metrics() és un no-op malgrat el nom i el docstring.
"""
from prometheus_client import REGISTRY


def _get_counter_value(path_label: str) -> float | None:
    """Helper: returns the value of the core_http_requests_total sample for a specific path."""
    for m in REGISTRY.collect():
        # m.name is 'core_http_requests' (without _total); the samples do include _total
        for s in m.samples:
            if (s.name == "core_http_requests_total"
                    and s.labels.get("path") == path_label):
                return s.value
    return None


def test_reset_metrics_actually_resets():
    """
    reset_metrics() must reset the counters/registries.
    Before the fix: it's a no-op that only logs a warning.
    After the fix: the counters return to 0.
    """
    from core.metrics import registry as reg

    # Increment the counter with a label unique to this test
    path_label = "/test_b243_unique_reset"
    reg.HTTP_REQUESTS_TOTAL.labels(
        method="GET", path=path_label, status="200"
    ).inc()

    # Check that the value is > 0 (the increment worked)
    before = _get_counter_value(path_label)
    assert before is not None and before > 0, (
        f"El comptador hauria de tenir valor > 0 abans del reset, però és {before}"
    )

    # Call reset_metrics()
    reg.reset_metrics()

    # After the reset, the counter must be 0 or absent
    after = _get_counter_value(path_label)
    reset_value = after if after is not None else 0.0
    assert reset_value == 0.0, (
        f"Després de reset_metrics() el comptador hauria de ser 0, però és {reset_value}"
    )
