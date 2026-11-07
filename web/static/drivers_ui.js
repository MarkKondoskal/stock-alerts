(function (root) {
  function selected(rows) {
    const valid = rows.filter(row => typeof row.ticker === 'string' && Number.isFinite(row.contribution_pp));
    const gains = valid.filter(row => row.contribution_pp > 0).sort((a,b) => b.contribution_pp-a.contribution_pp).slice(0,5);
    const losses = valid.filter(row => row.contribution_pp < 0).sort((a,b) => a.contribution_pp-b.contribution_pp).slice(0,5);
    return [...gains, ...losses.sort((a,b) => b.contribution_pp-a.contribution_pp)];
  }
  function render(info, {chartId, noteId, draw, clear, period}) {
    const note = document.getElementById(noteId);
    const shown = selected(info.drivers || []);
    clear(chartId);
    if (!shown.length) {
      note.textContent = info.drivers?.length ? 'No positive or negative contributions in this period.' : (info.drivers_note || 'Contribution data is not prepared yet. Refresh after the next dashboard preparation.');
      return;
    }
    draw(chartId, 'bar', {
      labels: shown.map(row => row.ticker),
      datasets: [{label: 'Portfolio contribution', data: shown.map(row => row.contribution_pp),
        backgroundColor: shown.map(row => row.contribution_pp > 0 ? '#34d399' : '#fb7185'), borderRadius: 4}]
    }, {indexAxis: 'y', plugins: {legend: {display: false}, tooltip: {callbacks: {
      label: context => `${context.parsed.x > 0 ? '+' : ''}${context.parsed.x.toFixed(3)} percentage points`
    }}}, scales: {x: {ticks: {color: '#aaa', callback: value => value+' pp'}, grid: {color: '#ffffff14'}},
      y: {ticks: {color: '#bbb'}, grid: {display: false}}}});
    note.textContent = `${period} · Up to five contributors and five detractors, in percentage points of portfolio return—not stock-price return. ${info.drivers_note || ''}`;
  }
  root.PerformanceDrivers = {render, selected};
})(typeof window === 'undefined' ? globalThis : window);
