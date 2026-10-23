
const $ = selector => document.querySelector(selector);

const fmt = (n, digits = 2) =>
  Number(n || 0).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });

const targetText = values =>
  Array.isArray(values) && values.length
    ? values.join(", ")
    : "—";

const directionTargets = (item, metric, direction) =>
  targetText(item.valuation_targets?.[metric]?.[direction]);

async function getPublicData(path) {
  const response = await fetch(path, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store"
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }

  return data;
}

function renderPortfolio(data) {
  const positions = data.positions || [];

  $("#position-count").textContent = data.position_count ?? positions.length;

  const largest = positions.reduce(
    (best, item) =>
      Number(item.allocation_pct) > Number(best?.allocation_pct ?? -1)
        ? item
        : best,
    null
  );

  $("#largest-allocation").textContent =
    largest ? `${fmt(largest.allocation_pct)}%` : "—";

  $("#largest-ticker").textContent =
    largest ? largest.ticker : "No positions";

  $("#allocation-note").textContent =
    `Allocation based on ${data.allocation_basis || "recorded cost basis"}. ` +
    "It does not yet represent live market-value allocation.";

  $("#portfolio-rows").innerHTML = positions.map(position => {
    const weight = Math.max(
      0,
      Math.min(100, Number(position.allocation_pct) || 0)
    );

    return `
      <tr>
        <td><span class="ticker">${position.ticker}</span></td>
        <td class="num">${fmt(weight)}%</td>
        <td class="num">$${fmt(position.avg_price)}</td>
        <td>
          <div style="display:flex;align-items:center;gap:10px;min-width:110px">
            <div style="height:7px;flex:1;background:#252a34;border-radius:5px;overflow:hidden">
              <div style="height:100%;width:${weight}%;background:#818cf8;border-radius:5px"></div>
            </div>
            <small>${fmt(weight)}%</small>
          </div>
        </td>
      </tr>`;
  }).join("") || `
    <tr><td colspan="4" class="muted">No holdings available.</td></tr>`;
}

function renderWatchlist(watchlist) {
  const entries = Object.entries(watchlist || {}).sort(
    ([a], [b]) => a.localeCompare(b)
  );

  $("#watchlist-count").textContent = entries.length;

  $("#watchlist-rows").innerHTML = entries.map(([ticker, item]) => `
    <tr>
      <td><span class="ticker">${ticker}</span></td>
      <td>${targetText(item.price_targets)}</td>
      <td>${directionTargets(item, "FxPE", "trim")}</td>
      <td>${directionTargets(item, "FxPE", "buy")}</td>
      <td>${directionTargets(item, "PE", "trim")}</td>
      <td>${directionTargets(item, "PE", "buy")}</td>
      <td>${directionTargets(item, "P/S", "trim")}</td>
      <td>${directionTargets(item, "P/S", "buy")}</td>
    </tr>`
  ).join("") || `
    <tr><td colspan="8" class="muted">No watchlist tickers found.</td></tr>`;
}

function renderWorkflows(runs) {
  $("#workflow-list").innerHTML = runs.map(run => {
    const status = run.status === "completed"
      ? (run.conclusion || "completed")
      : (run.status || "unknown");

    const safeUrl = (() => {
      try {
        const url = new URL(run.html_url);
        return url.hostname === "github.com" ? url.href : "";
      } catch {
        return "";
      }
    })();

    return `
      <div class="workflow">
        <div>
          <b>${escapeHtml(run.name || "Workflow")}</b>
          <small>
            ${escapeHtml(run.created_at
              ? new Date(run.created_at).toLocaleString()
              : "Time unavailable")}
            · ${safeUrl
              ? `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" style="color:#a5b4fc">View run ↗</a>`
              : "Run details unavailable"}
          </small>
        </div>
        <span class="pill">${escapeHtml(status)}</span>
      </div>`;
  }).join("") || '<p class="muted">No workflow runs found.</p>';
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

async function refreshPublicDashboard() {
  $("#public-error").textContent = "";

  try {
    const [portfolio, watchlist, workflows] = await Promise.all([
      getPublicData("/api/public/portfolio"),
      getPublicData("/api/public/watchlist"),
      getPublicData("/api/public/workflows")
    ]);

    renderPortfolio(portfolio);
    renderWatchlist(watchlist);
    renderWorkflows(workflows);

    $("#last-updated").textContent =
      `Last refreshed: ${new Date().toLocaleString()}`;
  } catch (error) {
    $("#public-error").textContent =
      `Could not load public data: ${error.message}`;
  }
}

$("#refresh").addEventListener("click", refreshPublicDashboard);

refreshPublicDashboard();
