/* Read-only macro dashboard shared by /public and the authenticated site. */
(() => {
  'use strict';
  const state = { public: { loaded: false, loading: false, filter: 'All' }, private: { loaded: false, loading: false, filter: 'All' } };
  let request = null;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const day = value => {
    if (!value) return 'Unknown';
    const str = String(value);
    const date = new Date(str.length === 10 ? str + 'T12:00:00Z' : str);
    return Number.isNaN(date.getTime()) ? str.slice(0, 22) : date.toLocaleDateString('en-US', {year:'numeric', month:'short', day:'numeric', timeZone:'UTC'});
  };
  const fixed = (value, digits = 1) => {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString('en-US',{ minimumFractionDigits:digits, maximumFractionDigits:digits }) : '—';
  };
  function blocks(id) {
    const el = document.getElementById('sentiment-' + id);
    if (!el) return null;
    if (!el.dataset.mounted) {
      el.innerHTML = `<div class="sentiment-head">
        <div><h1>Market Sentiment <span class="sentiment-accent">&amp; Economy</span></h1>
        <p>Market mood, volatility, inflation, jobs and monetary policy — public US market data.</p></div>
        <button type="button" class="sentiment-refresh" data-action="refresh">↻ Refresh data</button>
      </div>
      <div class="sentiment-update" role="status" aria-live="polite">Loading latest indicators…</div>
      <div class="sentiment-highlights">
        <article class="sentiment-stat"><div class="sentiment-stat-top"><span>Volatility index</span><a href="https://fred.stlouisfed.org/series/VIXCLS" target="_blank" rel="noopener noreferrer">VIX ↗</a></div><div data-role="vix" class="sentiment-stat-content"><span class="sentiment-empty">Loading…</span></div></article>
        <article class="sentiment-stat"><div class="sentiment-stat-top"><span>Investor sentiment</span><a href="https://www.cnn.com/markets/fear-and-greed" target="_blank" rel="noopener noreferrer">CNN ↗</a></div><div data-role="fear" class="sentiment-stat-content"><span class="sentiment-empty">Loading…</span></div></article>
      </div>
      <div class="sentiment-report-panel">
        <div class="sentiment-reports-head"><div><h2>Latest economic reports</h2><p>Most recent observation for each indicator — the period below is <strong>not</strong> the announcement date.</p></div><span class="sentiment-reports-count" data-role="count"></span></div>
        <div class="sentiment-categories" role="group" aria-label="Filter economic indicators">
          ${['All','Inflation','Jobs','Growth','Federal Reserve'].map(label => `<button type="button" data-filter="${label}" class="sentiment-category${label==='All'?' active':''}" aria-pressed="${label==='All'}">${label}</button>`).join('')}
        </div>
        <div class="sentiment-table-wrap"><table class="sentiment-table"><thead><tr><th>Indicator</th><th>Latest reading</th><th>Reference period</th><th>Source</th></tr></thead><tbody data-role="rows"><tr><td colspan="4" class="sentiment-empty">Loading economic figures…</td></tr></tbody></table></div>
      </div>
      <p class="sentiment-disclaimer">Sources: Yahoo Finance / FRED (VIX), CNN Fear &amp; Greed, Federal Reserve Bank of St. Louis (FRED). Inflation figures are year-over-year changes; nonfarm payrolls show the monthly change. Numbers may be revised or delayed. Unavailable indicators are not estimated.</p>`;
      el.dataset.mounted = 'true';
      el.querySelector('[data-action=refresh]').addEventListener('click', () => load(id, true));
      el.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
        state[id].filter = button.dataset.filter;
        el.querySelectorAll('[data-filter]').forEach(b => {
          const selected = b === button;
          b.classList.toggle('active', selected);
          b.setAttribute('aria-pressed', String(selected));
        });
        if (state[id].data) renderReports(id, state[id].data.reports || []);
      }));
    }
    return el;
  }
  function renderReports(id, reports) {
    const el = blocks(id);
    const shown = reports.filter(row => state[id].filter === 'All' || row.category === state[id].filter);
    el.querySelector('[data-role=count]').textContent = `${shown.length} indicators`;
    el.querySelector('[data-role=rows]').innerHTML = shown.length ? shown.map(row => {
      let value = fixed(row.value, row.id === 'PAYEMS' || row.id === 'ICSA' ? 0 : row.id === 'UNRATE' ? 1 : 2);
      if (row.id === 'DFEDTARU' && row.lower != null) value = `${fixed(row.lower,2)}–${fixed(row.value,2)}`;
      const unit = escape(row.unit || '');
      const label = escape(row.title);
      const source = typeof row.source_url === 'string' && /^https:\/\/fred\.stlouisfed\.org\/series\/[A-Z0-9]+$/.test(row.source_url)
        ? `<a href="${row.source_url}" target="_blank" rel="noopener noreferrer">FRED ↗</a>` : 'FRED';
      return `<tr><td><span class="sentiment-item-label">${label}</span><span class="sentiment-item-sub">${escape(row.description || row.category)}${row.stale ? ' · cached reading' : ''}</span></td>
        <td class="sentiment-item-value">${value}<span class="sentiment-unit"> ${unit}</span></td><td class="sentiment-date">${escape(day(row.period))}</td><td class="sentiment-source">${source}</td></tr>`;
    }).join('') : `<tr><td colspan="4" class="sentiment-empty">${reports.length ? 'No indicators in this category.' : 'No economic data available from FRED. Try again later.'}</td></tr>`;
  }
  function render(id, data) {
    const el = blocks(id);
    state[id].data = data;
    const vix = el.querySelector('[data-role=vix]');
    const fear = el.querySelector('[data-role=fear]');
    if (data.vix) {
      const v = data.vix.value;
      const level = v < 15 ? 'Low volatility' : v < 25 ? 'Moderate volatility' : v < 35 ? 'Elevated volatility' : 'High volatility';
      const marker = Math.min(100, Math.max(0, (v/50)*100));
      vix.innerHTML = `<div class="sentiment-value">${fixed(v,2)}<span class="sentiment-status">${escape(level)}</span></div>
        <div class="sentiment-meter sentiment-vix-meter"><span style="left:${marker}%"></span></div>
        <div class="sentiment-stat-footer">${escape(data.vix.frequency || 'Market quote')} · ${escape(day(data.vix.as_of))}${data.vix.stale ? ' · cached' : ''}</div>`;
    } else vix.innerHTML = `<div class="sentiment-value sentiment-unavailable">Unavailable</div><p class="sentiment-stat-footer">VIX provider did not return a valid reading.</p>`;
    if (data.fear_greed) {
      const v = data.fear_greed.value;
      const marker = Math.min(100, Math.max(0,v));
      fear.innerHTML = `<div class="sentiment-value">${fixed(v,1)}<span class="sentiment-status">${escape(data.fear_greed.rating)}</span></div>
        <div class="sentiment-meter sentiment-fear-meter"><span style="left:${marker}%"></span></div>
        <div class="sentiment-meter-labels"><span>Extreme fear</span><span>Neutral</span><span>Extreme greed</span></div>
        <div class="sentiment-stat-footer">${escape(day(data.fear_greed.as_of))}${data.fear_greed.stale ? ' · cached' : ''}</div>`;
    } else fear.innerHTML = `<div class="sentiment-value sentiment-unavailable">Unavailable</div><p class="sentiment-stat-footer">CNN did not return a valid reading.</p>`;
    renderReports(id, data.reports || []);
    const timestamp = new Date(data.generated_at);
    const timeStr = Number.isNaN(timestamp.getTime()) ? '' : timestamp.toLocaleString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'UTC'}) + ' UTC';
    const missing = [!data.vix ? 'VIX' : null, !data.fear_greed ? 'Fear & Greed' : null, !(data.reports || []).length ? 'economic data' : null].filter(Boolean);
    const summary = missing.length ? `Some data unavailable (${missing.join(', ')}).` : 'Market data loaded.';
    el.querySelector('.sentiment-update').textContent = `${summary}${timeStr ? ' Checked ' + timeStr + '.' : ''} Economic dates show reference periods, not publication dates.`;
  }
  async function load(id, force = false) {
    const el = blocks(id);
    if (!el || state[id].loading) return;
    if (state[id].loaded && !force) return;
    state[id].loading = true;
    const button = el.querySelector('.sentiment-refresh');
    button.disabled = true;
    button.textContent = 'Refreshing…';
    el.querySelector('.sentiment-update').textContent = 'Fetching market and economic indicators…';
    try {
      if (!request) request = fetch('/api/public/sentiment', {cache: 'no-store', headers:{Accept:'application/json'}})
        .then(async res => {
          if (!res.ok) throw new Error(`Market-data service unavailable (HTTP ${res.status})`);
          return res.json();
        }).finally(() => { request = null; });
      const data = await request;
      render(id, data);
      state[id].loaded = true;
    } catch (error) {
      el.querySelector('.sentiment-update').textContent = `Unable to refresh: ${error.message}. Existing readings, if any, are unchanged.`;
    } finally {
      state[id].loading = false;
      button.disabled = false;
      button.textContent = '↻ Refresh data';
    }
  }
  window.StockSentiment = {load};
})();
