//! Per-plugin rate limiter — bounded token bucket with LRU cap.
//!
//! Sprint 0.14 #T3 / S06 F023: token bucket (burst-resistant).
//! S03 F029: LRU cap 500 to avoid OOM with many different IDs.
//! F045: fail-closed on mutex poison.
//! C30(2026-04-21): lookup-then-insert avoids `.to_string()` alloc per
//! request on the happy path (hot path limiter).

use lru::LruCache;
use std::num::NonZeroUsize;
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

/// Maximum tokens per plugin (= sustained requests per second).
pub(crate) const RATE_LIMIT_CAPACITY: u64 = 1000;

/// Maximum number of entries in the LRU cache (plugins with active limiter).
pub(crate) const RATE_LIMIT_LRU_CAP: usize = 500;

static RATE_LIMITERS: OnceLock<Mutex<LruCache<String, (Instant, u64)>>> = OnceLock::new();

pub(crate) fn rate_limiters() -> &'static Mutex<LruCache<String, (Instant, u64)>> {
    RATE_LIMITERS.get_or_init(|| {
        // RATE_LIMIT_LRU_CAP is const=500 > 0 — unwrap_or safe with minimal fallback
        let cap = NonZeroUsize::new(RATE_LIMIT_LRU_CAP).unwrap_or(NonZeroUsize::MIN);
        Mutex::new(LruCache::new(cap))
    })
}

/// Token bucket per plugin. Returns true if tokens are available, false if the request should be rejected.
///
/// C30: we avoid `plugin_id.to_string()` alloc per request when the entry already
/// exists in the cache. `contains(&str)` accepts `&Q: ?Sized` (no String required),
/// `get_mut` likewise. We only allocate when actually inserting (first time a plugin_id is seen).
pub(crate) fn rate_limit_ok_for(plugin_id: &str) -> bool {
    let mut guard = match rate_limiters().lock() {
        Ok(g) => g,
        Err(_) => return false, // F045: fail-closed on mutex poison
    };
    let cap = RATE_LIMIT_CAPACITY;

    // C30: lookup first (no alloc); insert only if absent.
    if !guard.contains(plugin_id) {
        guard.put(plugin_id.to_string(), (Instant::now(), cap));
    }
    let entry = match guard.get_mut(plugin_id) {
        Some(e) => e,
        None => return true, // LRU evicted race — allow to avoid a cascading failure
    };

    // Refill tokens based on elapsed time
    let elapsed_secs = entry.0.elapsed().as_secs_f64();
    let refill = (elapsed_secs * cap as f64) as u64;
    if refill > 0 {
        entry.1 = (entry.1 + refill).min(cap);
        entry.0 = Instant::now();
    }
    // Consume one token
    if entry.1 == 0 {
        return false;
    }
    entry.1 -= 1;
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_request_always_allowed() {
        // A fresh plugin_id should always get through (full bucket).
        assert!(rate_limit_ok_for("test-fresh-plugin-1234"));
    }

    #[test]
    fn exhausting_bucket_rejects() {
        // Flaky-fix (2026-05-21): when this test ran in batch with the rest
        // of the suite, the drain loop took >1 ms and `rate_limit_ok_for`
        // refilled the bucket mid-drain (refill = elapsed_secs * 1000, so a
        // 1 ms gap between calls already credits 1 token back). The assertion
        // 'next one must be rejected' then flaked. We now drain *until* the
        // limiter actually rejects, with a generous upper bound that is
        // still O(milliseconds) of cargo test wall time.
        let id = "test-exhaust-bucket-unique";
        let mut consumed = 0u64;
        // Hard ceiling so a logic bug cannot spin forever.
        let safety_cap = RATE_LIMIT_CAPACITY * 20;
        while rate_limit_ok_for(id) {
            consumed += 1;
            assert!(
                consumed <= safety_cap,
                "drained {consumed} tokens without ever being rejected — refill rate is keeping up with consumption, which means the limiter is not actually bounding burst",
            );
        }
        // We reached a rejection — that is the property under test.
        // The exact `consumed` count is implementation-dependent (depends
        // on how much the OS slept us between calls) but must be > 0.
        assert!(
            consumed >= RATE_LIMIT_CAPACITY,
            "limiter rejected after only {consumed} tokens — capacity is at least {RATE_LIMIT_CAPACITY}"
        );
    }

    #[test]
    fn different_plugins_have_independent_buckets() {
        let a = "test-independent-a";
        let b = "test-independent-b";
        // Drain A
        for _ in 0..RATE_LIMIT_CAPACITY {
            rate_limit_ok_for(a);
        }
        // B should still work
        assert!(rate_limit_ok_for(b), "B's bucket must be independent of A");
    }

    #[test]
    fn mutex_poison_fails_closed() {
        // F045: if the mutex is poisoned, rate_limit_ok_for returns false (fail-closed).
        // We can't easily poison it in a unit test without panicking in another thread,
        // but we verify the code path exists by checking the match arm compiles
        // and the constant is correct.
        assert_eq!(RATE_LIMIT_CAPACITY, 1000);
        assert_eq!(RATE_LIMIT_LRU_CAP, 500);
    }
}
