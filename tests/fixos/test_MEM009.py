"""MEM-009 — get_config must return an independent copy.

PROFILES holds module-level mutable MemoryConfig; previously get_config
returned them by reference, so mutating the result corrupted the singleton for
all consumers. Now it returns a deepcopy.
"""


def test_mem009_get_config_returns_independent_copy():
    """Mutating the result of get_config must NOT affect the PROFILES singleton
    nor a second call (each caller gets an independent copy)."""
    from memory.memory.config import get_config, PROFILES

    cfg_a = get_config("m1_8gb")
    # mutació hostil sobre la còpia rebuda
    cfg_a.dedup_refresh_threshold = 0.123
    cfg_a.budgets.episodic_max = 1
    cfg_a.profile_name = "MUTAT"

    # the singleton has not been touched
    assert PROFILES["m1_8gb"].dedup_refresh_threshold != 0.123
    assert PROFILES["m1_8gb"].budgets.episodic_max != 1
    assert PROFILES["m1_8gb"].profile_name == "m1_8gb"

    # una segona crida tampoc veu la mutació
    cfg_b = get_config("m1_8gb")
    assert cfg_b.dedup_refresh_threshold != 0.123
    assert cfg_b.budgets.episodic_max != 1
    assert cfg_b is not cfg_a


def test_mem009_values_still_correct():
    """The deepcopy preserves the profile values (it doesn't degrade the read)."""
    from memory.memory.config import get_config

    cfg = get_config("m1_8gb")
    assert cfg.profile_name == "m1_8gb"
    assert cfg.budgets.episodic_max == 1000
    assert cfg.retrieve.max_tokens_cap == 800
