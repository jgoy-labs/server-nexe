// MutationObserver protection per Lucide (race condition fix)
if (typeof MutationObserver !== 'undefined') {
    var _origObserve = MutationObserver.prototype.observe;
    MutationObserver.prototype.observe = function(target, options) {
        if (!(target instanceof Node)) return;
        return _origObserve.call(this, target, options);
    };
}

// Initialize Lucide icons after DOM load
document.addEventListener('DOMContentLoaded', function() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
});
