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
  function tradeFeed(trades) {
    const feed = element('ul');
    feed.className = 'trade-feed';
    const dates = new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeZone: 'UTC'});
    for (const trade of trades) {
      const buy = trade.action === 'BUY';
      const entry = element('li');
      entry.className = 'trade-feed-entry';
      const badge = element('span', buy ? 'BUY' : 'SELL');
      badge.className = 'trade-feed-badge ' + (buy ? 'trade-feed-buy' : 'trade-feed-sell');
      const body = element('div');
      body.className = 'trade-feed-body';
      body.append(element('strong', (buy ? 'Bought ' : 'Sold ') + trade.ticker));
      if (trade.position_change) {
        const change = element('p', trade.position_change);
        change.className = 'trade-feed-change';
        body.append(change);
      }
      if (trade.note) {
        const note = element('p', trade.note);
        note.className = 'trade-feed-note';
        body.append(note);
      }
      const time = element('time');
      if (trade.date) {
        const date = new Date(trade.date + 'T00:00:00Z');
        time.dateTime = trade.date;
        time.textContent = Number.isNaN(date.getTime()) ? trade.date : dates.format(date);
      }
      entry.append(badge, body, time);
      feed.append(entry);
    }
    return feed;
  }
  window.loadPublicTradeActivity = async () => {
    const node = document.getElementById('public-trade-activity');
    node.replaceChildren(element('p', 'Loading trade activity…'));
    try {
      const response = await fetch('/api/public/trade-activity', {cache: 'no-store'});
      if (!response.ok) throw new Error('Trade activity temporarily unavailable.');
      const {trades} = await response.json();
      node.replaceChildren(trades.length
        ? tradeFeed(trades)
        : element('p', 'No buys or sells are available.'));
    } catch {
      node.replaceChildren(element('p', 'Trade activity temporarily unavailable.'));
    }
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
