/**
 * Security Module — Status Page JS
 * Server Nexe 0.9.0
 *
 * Fetch /security/info i /security/health per mostrar estat.
 */

(function() {
  const BASE = window.location.origin;

  async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  function setError(msg) {
    const el = document.getElementById('error');
    el.textContent = msg;
    el.style.display = 'block';
  }

  async function loadInfo() {
    try {
      const data = await fetchJSON(`${BASE}/security/info`);
      const grid = document.getElementById('info-grid');
      grid.innerHTML = `
        <dt>Name</dt><dd>${data.name || '-'}</dd>
        <dt>Version</dt><dd>${data.version || '-'}</dd>
        <dt>Type</dt><dd>${data.type || '-'}</dd>
        <dt>Initialized</dt><dd>${data.initialized ? 'Yes' : 'No'}</dd>
        <dt>Description</dt><dd>${data.description || '-'}</dd>
      `;
      const list = document.getElementById('endpoints-list');
      list.innerHTML = (data.endpoints || [])
        .map(e => `<li><code>${e}</code></li>`)
        .join('');
    } catch (e) {
      setError('Failed to load info: ' + e.message);
    }
  }

  async function loadHealth() {
    try {
      const data = await fetchJSON(`${BASE}/security/health`);
      const status = data.status || 'unknown';
      document.getElementById('health-status').innerHTML =
        `<span class="status ${status}">${status}</span>`;
      document.getElementById('health-message').textContent = data.message || '';

      const checksEl = document.getElementById('health-checks');
      if (data.checks && data.checks.length) {
        checksEl.innerHTML = data.checks.map(c =>
          `<div class="check-item">
            <span class="check-dot ${c.status}"></span>
            <span>${c.name}: ${c.message}</span>
          </div>`
        ).join('');
      }
    } catch (e) {
      document.getElementById('health-status').innerHTML =
        '<span class="status unknown">unreachable</span>';
    }
  }

  loadInfo();
  loadHealth();
  // Refresh health cada 30s
  setInterval(loadHealth, 30000);
})();
