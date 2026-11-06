(() => {
  const element = (tag, value) => {
    const node = document.createElement(tag);
    if (value != null) node.textContent = value;
    return node;
  };
  function table(headers, rows) {
    const wrap = element('div');
    wrap.className = 'tablewrap public-table-wrap';
    const result = element('table');
    result.className = 'public-table';
    const head = result.createTHead().insertRow();
    for (const header of headers) head.append(element('th', header));
    const body = result.createTBody();
    for (const row of rows) {
      const tr = body.insertRow();
      for (const value of row) {
        const cell = tr.insertCell();
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value ?? 'Unavailable';
      }
    }
    wrap.append(result);
    return wrap;
  }
  function sourceLink(url, label) {
    const link = element('a', label);
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  }
  const local = stamp => stamp ? new Date(stamp).toLocaleString() : 'Unavailable';
  const percent = value => value == null ? 'Unavailable' : value.toFixed(2) + '%';
  const charts = {};
  window.renderAdvanced = (scope, data) => {
    const node = document.getElementById('advanced-' + scope);
    charts[scope]?.destroy();
    delete charts[scope];
    node.replaceChildren(element('h3', 'Risk and return attribution'));
    const metrics = data?.advanced;
    if (!metrics || metrics.max_drawdown_pct == null) {
      node.append(element('p', data ? 'Unavailable for the selected period.' : 'Loading…'));
      return;
    }
    const rolling = metrics.rolling.at(-1);
    node.append(element('p', [
      'Max drawdown ' + percent(metrics.max_drawdown_pct),
      'Annualized volatility ' + percent(metrics.volatility_pct),
      '21-session return ' + percent(rolling?.portfolio_pct),
      '21-session SPY ' + percent(rolling?.spy_pct),
    ].join(' · ')));
    if (typeof Chart !== 'undefined') {
      const frame = element('div');
      frame.style.height = '220px';
      frame.style.position = 'relative';
      const canvas = element('canvas');
      canvas.setAttribute('aria-label', 'Drawdown and rolling 21-session returns');
      frame.append(canvas);
      node.append(frame);
      const dates = metrics.drawdowns.map(point => point.date);
      const rollingByDate = new Map(metrics.rolling.map(point => [point.date, point]));
      charts[scope] = new Chart(canvas, {
        type: 'line',
        data: {labels: dates, datasets: [
          {label: 'Drawdown', data: metrics.drawdowns.map(point => point.value), borderColor: '#f59e0b'},
          {label: 'Rolling portfolio', data: dates.map(day => rollingByDate.get(day)?.portfolio_pct ?? null), borderColor: '#2dd4bf'},
          {label: 'Rolling SPY', data: dates.map(day => rollingByDate.get(day)?.spy_pct ?? null), borderColor: '#bb92ef'},
        ]},
        options: {responsive: true, maintainAspectRatio: false, elements: {point: {radius: 0}},
          scales: {x: {ticks: {maxTicksLimit: 7}}, y: {ticks: {callback: value => value + '%'}}}},
      });
    }
    const rows = metrics.contributions;
    if (!rows.length) {
      node.append(element('p', 'Contribution by stock is unavailable for this period.'));
      return;
    }
    const isPrivate = scope === 'private';
    const amount = new Intl.NumberFormat(undefined, {style: 'currency', currency: data.currency});
    const headers = ['Ticker', 'Contribution (pp)'];
    if (isPrivate) headers.push('Estimated market P/L');
    const details = element('details');
    details.append(element('summary', 'Contribution by stock'),
      element('p', 'Dated holdings and close-to-close price moves. Includes FX in the selected currency. Excludes cash, fees and ordinary dividends.'),
      table(headers, rows.map(row => [row.ticker, row.contribution_pp.toFixed(3),
        ...(isPrivate ? [amount.format(row.market_move_amount)] : [])])));
    node.append(details);
  };

  let calendarRequest;
  window.loadEconomicCalendar = async scope => {
    const node = document.getElementById('calendar-' + scope);
    node.replaceChildren(element('h2', 'US economic release calendar'), element('p', 'Loading…'));
    try {
      if (!calendarRequest) calendarRequest = fetch('/api/public/economic-calendar')
        .then(response => {
          if (!response.ok) throw new Error('Calendar unavailable');
          return response.json();
        }).finally(() => { calendarRequest = null; });
      const data = await calendarRequest;
      const titles = ['Release', 'Local time', 'Reference', 'Previous', 'Forecast', 'Actual', 'Sources'];
      node.replaceChildren(element('h2', 'US economic release calendar'));
      if (data.schedule_warnings.length) node.append(element('p',
        'Live schedule unavailable for ' + data.schedule_warnings.join(', ') + '. Showing verified fallback dates where available.'));
      if (!data.readings_configured) node.append(element('p', 'Economic readings require server configuration.'));
      for (const upcoming of [true, false]) {
        const rows = data.events.filter(event => event.upcoming === upcoming);
        if (!upcoming) rows.reverse();
        node.append(element('h3', upcoming ? 'Upcoming' : 'Recent releases'));
        if (!rows.length) {
          node.append(element('p', 'No verified dates in this window.'));
          continue;
        }
        node.append(table(titles, rows.map(event => {
          const links = element('span');
          links.append(sourceLink(event.schedule_source, 'Schedule'), ' · ', sourceLink(event.reading_source, 'Readings'));
          return [event.name + (event.estimate ? ' · ' + event.estimate : ''), local(event.release),
            event.reference || 'Decision', event.previous, 'Unavailable', event.actual ?? (upcoming ? 'Pending' : 'Unavailable'), links];
        })));
      }
    } catch {
      node.replaceChildren(element('h2', 'US economic release calendar'), element('p', 'Calendar temporarily unavailable.'));
    }
  };

  window.loadSystemHealth = async () => {
    const node = document.getElementById('system-health');
    node.replaceChildren(element('h2', 'Scheduled checks'), element('p', 'Loading…'));
    try {
      const result = await api('/api/private/system-health');
      node.replaceChildren(element('h2', 'Scheduled checks'), table(
        ['Check', 'Latest run', 'Last successful run', 'Status'],
        result.workflows.map(row => [row.name, local(row.latest_at), local(row.last_success_at),
          row.unavailable ? 'Unavailable' : [row.latest_status, row.latest_outcome,
            row.failed ? 'Workflow failed' : null, row.stale ? 'Stale or never succeeded' : null].filter(Boolean).join(' · ')])),
        element('h3', 'Portfolio data freshness'),
        table(['History', 'Through', 'Status'], result.data.map(row =>
          [row.name, row.through, row.unavailable ? 'Unavailable' : row.stale ? 'Stale' : 'Current'])));
    } catch (error) {
      node.replaceChildren(element('h2', 'Scheduled checks'), element('p', error.message));
    }
  };
})();
