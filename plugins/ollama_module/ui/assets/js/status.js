const esc = (s) => { const d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; };

(function() {
  const BASE = window.location.origin;
  async function fetchJSON(url) {
    const r = await fetch(url); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json();
  }
  async function loadInfo() {
    try {
      const d = await fetchJSON(`${BASE}/ollama/info`);
      document.getElementById('info-grid').innerHTML = `
        <dt>Name</dt><dd>${esc(d.name)||'-'}</dd>
        <dt>Version</dt><dd>${esc(d.version)||'-'}</dd>
        <dt>Base URL</dt><dd>${esc(d.base_url)||'-'}</dd>
        <dt>Initialized</dt><dd>${d.initialized?'Yes':'No'}</dd>`;
    } catch(e) { document.getElementById('error').textContent=e.message; document.getElementById('error').style.display='block'; }
  }
  async function loadHealth() {
    try {
      const d = await fetchJSON(`${BASE}/ollama/health`);
      const s = d.status||'unknown';
      document.getElementById('health-status').innerHTML = `<span class="status ${s}">${esc(s)}</span> ${esc(d.message||'')}`;
    } catch { document.getElementById('health-status').innerHTML='<span class="status unknown">unreachable</span>'; }
  }
  async function loadModels() {
    try {
      const d = await fetchJSON(`${BASE}/ollama/api/models`);
      const list = document.getElementById('model-list');
      if (d.models && d.models.length) {
        list.innerHTML = d.models.map(m => `<li>${esc(m.name||m.model||'?')} (${((m.size||0)/1e9).toFixed(1)} GB)</li>`).join('');
      } else { list.innerHTML = '<li>No models installed</li>'; }
    } catch { document.getElementById('model-list').innerHTML = '<li>Cannot connect to Ollama</li>'; }
  }
  loadInfo(); loadHealth(); loadModels();
  setInterval(loadHealth, 30000);
})();
