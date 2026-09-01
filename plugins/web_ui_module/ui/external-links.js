// Open external links via sidecar /ui/open-external endpoint.
// Tauri v2 isolation prevents __TAURI_INTERNALS__ at http://127.0.0.1;
// a sidecar HTTP call is the only reliable cross-platform approach.
//
// External file (not inline): script-src 'self' allows this without
// 'unsafe-inline' in any mode, standalone or Tauri sidecar (#127 follow-up).
(function () {
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href");
    if (!href || !/^https?:\/\//.test(href)) return;
    e.preventDefault();
    var key = localStorage.getItem("nexe_api_key") || "";
    fetch("/ui/open-external?url=" + encodeURIComponent(href), {
      headers: key ? { "X-API-Key": key } : {}
    }).catch(function () {});
  });
})();
