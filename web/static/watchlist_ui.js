(function (root) {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = value => typeof value === 'number' && Number.isFinite(value) && value > 0;
  function price(market = {}) {
    const value = finite(market.price) ? `${esc(market.currency || '')} ${market.price.toLocaleString(undefined, {maximumFractionDigits: 2})}` : 'Unavailable';
    const when = market.price_as_of ? new Date(market.price_as_of).toLocaleString() : market.fetched_at ? `Fetched ${new Date(market.fetched_at).toLocaleString()}; quote time unavailable` : 'Waiting for market-data update';
    return `${value}<small class="watch-market-date">${esc(when)}</small>`;
  }
  function valuations(market = {}) {
    return [['PE','P/E'],['FxPE','Forward P/E'],['P/S','P/S']].map(([key, label]) =>
      `<span class="watch-metric">${label}: <b>${finite(market.valuations?.[key]) ? market.valuations[key].toFixed(2)+'×' : '—'}</b></span>`).join('');
  }
  function targetRules(entry) {
    const rules = (entry.price_targets || []).map(target => ['PRICE','buy',target]);
    for (const [metric, raw] of Object.entries(entry.valuation_targets || {})) {
      const directions = Array.isArray(raw) ? {trim: raw} : raw;
      for (const direction of ['buy','trim']) for (const target of directions[direction] || []) rules.push([metric,direction,target]);
    }
    return rules;
  }
  function nearest(entry, market = {}) {
    return Math.min(...targetRules(entry).map(([metric,direction,target]) => {
      const actual = metric === 'PRICE' ? market.price : market.valuations?.[metric];
      if (!finite(actual) || !finite(target)) return Infinity;
      if (direction === 'buy' ? actual <= target : actual >= target) return 0;
      return Math.abs(target / actual - 1);
    }));
  }
  function proximity(entry, market = {}) {
    return targetRules(entry).map(([metric,direction,target]) => {
      const actual = metric === 'PRICE' ? market.price : market.valuations?.[metric];
      const label = `${metric === 'PRICE' ? 'Price' : metric} ${direction} ${target}${metric === 'PRICE' ? '' : '×'}`;
      if (!finite(actual) || !finite(target)) return `<span class="watch-rule">${esc(label)}: —</span>`;
      const met = direction === 'buy' ? actual <= target : actual >= target;
      const change = (target / actual - 1) * 100;
      const near = !met && Math.abs(change) <= 5 + 1e-9;
      return `<span class="watch-rule ${met ? 'watch-met' : near ? 'watch-near' : ''}"><span class="watch-rule-label">${esc(label)}:</span> <span class="watch-rule-distance">${met ? 'Condition met' : `${near ? 'Near · ' : ''}${Math.abs(change).toFixed(1)}% ${change < 0 ? 'fall' : 'rise'} needed`}</span></span>`;
    }).join('') || '<span class="muted">No targets</span>';
  }
  root.WatchlistUI = {price, valuations, proximity, nearest};
})(typeof window === 'undefined' ? globalThis : window);
