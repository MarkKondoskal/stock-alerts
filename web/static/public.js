
"use strict";

const API = {
    portfolio: "/api/public/portfolio",
    watchlist: "/api/public/watchlist",
};

const elements = {
    holdingsTab: document.getElementById("holdingsTab"),
    watchlistTab: document.getElementById("watchlistTab"),
    holdingsPanel: document.getElementById("holdingsPanel"),
    watchlistPanel: document.getElementById("watchlistPanel"),

    holdingsBody: document.getElementById("holdingsBody"),
    watchlistBody: document.getElementById("watchlistBody"),

    holdingCount: document.getElementById("holdingCount"),
    allocationBasis: document.getElementById("allocationBasis"),
    watchlistCount: document.getElementById("watchlistCount"),

    refreshButton: document.getElementById("refreshPublic"),
    message: document.getElementById("publicMessage"),
};

let cachedPortfolio = null;
let cachedWatchlist = null;


/* -------------------------
   General helpers
------------------------- */

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => {
        const entities = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;",
        };

        return entities[character];
    });
}

function asArray(payload, possibleKeys = []) {
    if (Array.isArray(payload)) {
        return payload;
    }

    if (!payload || typeof payload !== "object") {
        return [];
    }

    for (const key of possibleKeys) {
        if (Array.isArray(payload[key])) {
            return payload[key];
        }
    }

    return [];
}

function formatNumber(value, decimals = 2) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

function formatPrice(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return "$" + formatNumber(number, 2);
}

function showMessage(message, isError = false) {
    elements.message.textContent = message;
    elements.message.hidden = !message;
    elements.message.classList.toggle("error", isError);
}

function setLoading(isLoading) {
    elements.refreshButton.disabled = isLoading;
    elements.refreshButton.textContent = isLoading
        ? "Refreshing…"
        : "Refresh data";
}

async function fetchJson(url) {
    const response = await fetch(url, {
        method: "GET",
        headers: {
            Accept: "application/json",
        },
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error(`Request failed (${response.status}): ${url}`);
    }

    return response.json();
}


/* -------------------------
   Tab navigation
------------------------- */

function activateTab(tabName, moveFocus = false) {
    const showHoldings = tabName === "holdings";

    elements.holdingsTab.setAttribute(
        "aria-selected",
        String(showHoldings)
    );
    elements.watchlistTab.setAttribute(
        "aria-selected",
        String(!showHoldings)
    );

    elements.holdingsTab.tabIndex = showHoldings ? 0 : -1;
    elements.watchlistTab.tabIndex = showHoldings ? -1 : 0;

    elements.holdingsPanel.hidden = !showHoldings;
    elements.watchlistPanel.hidden = showHoldings;

    if (moveFocus) {
        (showHoldings
            ? elements.holdingsTab
            : elements.watchlistTab
        ).focus();
    }
}

elements.holdingsTab.addEventListener("click", () => {
    activateTab("holdings");
});

elements.watchlistTab.addEventListener("click", () => {
    activateTab("watchlist");
});

for (const [tab, name] of [
    [elements.holdingsTab, "holdings"],
    [elements.watchlistTab, "watchlist"],
]) {
    tab.addEventListener("keydown", (event) => {
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
            event.preventDefault();

            const nextTab = name === "holdings"
                ? "watchlist"
                : "holdings";

            activateTab(nextTab, true);
        }

        if (event.key === "Home") {
            event.preventDefault();
            activateTab("holdings", true);
        }

        if (event.key === "End") {
            event.preventDefault();
            activateTab("watchlist", true);
        }
    });
}


/* -------------------------
   Holdings tab
------------------------- */

function renderHoldings(payload) {
    const holdings = asArray(payload, ["holdings", "portfolio", "positions", "data"]);
    const meta = payload && !Array.isArray(payload) ? payload : {};
    elements.holdingCount.textContent = String(meta.position_count ?? holdings.length);
    elements.allocationBasis.textContent = meta.allocation_basis || "Cost basis";
    elements.holdingsBody.innerHTML = holdings.length ? [...holdings]
        .sort((a,b) => (b.allocation_pct || 0) - (a.allocation_pct || 0))
        .map(h => holdingRow(h)).join("")
        : `<tr><td colspan="6" class="public-empty">No holdings available.</td></tr>`;
}

function holdingRow(h) {
    const allocation = Number(h.allocation_pct) || 0;
    const price = h.current_price === null || h.current_price === undefined ? "—" : formatPrice(h.current_price);
    // Holdings table always shows return against recorded per-share cost,
    // not the selectable period from the gainers/losers bar chart.
    const cost = Number(h.cost_per_share ?? h.avg_price);
    const current = Number(h.current_price);
    const gain = Number.isFinite(cost) && cost > 0 &&
        h.current_price !== null && h.current_price !== undefined &&
        Number.isFinite(current) ? (current / cost - 1) * 100 : null;
    const gainText = gain === null ? "—" : `${gain > 0 ? "+" : ""}${formatNumber(gain)}%`;
    const gainClass = gain > 0 ? "return-positive" : gain < 0 ? "return-negative" : "";
    return `<tr>
        <td class="public-ticker">${escapeHtml(h.ticker || "—")}</td>
        <td>${escapeHtml(h.sector || "—")}</td>
        <td class="public-number">${formatPrice(h.cost_per_share ?? h.avg_price)}</td>
        <td class="public-number">${price}</td>
        <td><div class="public-allocation"><span class="public-number">${formatNumber(allocation)}%</span>
            <div class="public-allocation-track"><div class="public-allocation-fill" style="width:${Math.max(0, Math.min(100,allocation))}%"></div></div></div></td>
        <td class="public-number ${gainClass}">${gainText}</td>
    </tr>`;
}

/* -------------------------
   Watchlist target helpers
------------------------- */

function formatTargetValue(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    if (typeof value === "number" || (
        typeof value === "string" && value.trim() !== ""
        && Number.isFinite(Number(value))
    )) {
        return formatNumber(Number(value), 2);
    }

    if (typeof value === "object") {
        const parts = [];

        if (value.direction) {
            parts.push(String(value.direction));
        }

        if (value.type) {
            parts.push(String(value.type));
        }

        if (value.multiple !== undefined) {
            parts.push(`${value.multiple}x`);
        } else if (value.value !== undefined) {
            parts.push(String(value.value));
        }

        if (value.metric) {
            parts.push(String(value.metric));
        }

        return parts.join(" ") || "Target";
    }

    return String(value);
}

function renderPriceTargets(targets) {
    if (!Array.isArray(targets)) {
        if (targets && typeof targets === "object") {
            targets = Object.entries(targets).map(([key, value]) => ({
                label: key,
                value,
            }));
        } else if (targets !== null && targets !== undefined) {
            targets = [targets];
        } else {
            targets = [];
        }
    }

    const formatted = targets.map((target) => {
        if (typeof target === "number" || typeof target === "string") {
            return {
                label: "",
                value: formatTargetValue(target),
            };
        }

        return {
            label: target.label || target.type || target.direction || "",
            value: formatTargetValue(target),
        };
    });

    return renderTargetChips(formatted);
}

function renderValuationTargets(targets) {
    if (!targets || typeof targets !== "object") return renderTargetChips([]);
    const chips = [];
    for (const [metric, targetsByDirection] of Object.entries(targets)) {
        if (targetsByDirection && typeof targetsByDirection === "object" && !Array.isArray(targetsByDirection)) {
            for (const direction of ["buy", "trim"]) {
                for (const value of (Array.isArray(targetsByDirection[direction]) ? targetsByDirection[direction] : [])) {
                    chips.push({ label: `${metric} ${direction}`, value: `${formatTargetValue(value)}x` });
                }
            }
        } else {
            for (const value of (Array.isArray(targetsByDirection) ? targetsByDirection : [])) {
                chips.push({ label: metric, value: `${formatTargetValue(value)}x` });
            }
        }
    }
    return renderTargetChips(chips);
}

function renderTargetChips(targets) {
    if (!targets.length) {
        return '<span class="public-muted">—</span>';
    }

    return `
        <div class="public-target-list">
            ${targets.map((target) => {
                const label = target.label
                    ? `<strong>${escapeHtml(target.label)}:</strong> `
                    : "";

                return `
                    <span class="public-target">
                        ${label}${escapeHtml(target.value)}
                    </span>
                `;
            }).join("")}
        </div>
    `;
}


/* -------------------------
   Watchlist tab
------------------------- */

function renderWatchlist(payload) {
    const watchlist = asArray(payload, [
        "watchlist", "items", "data",
    ]);
    // Public endpoint returns an object keyed by ticker, not an array.
    if (!watchlist.length && payload && typeof payload === "object" && !Array.isArray(payload)) {
        for (const [ticker, entry] of Object.entries(payload)) {
            if (entry && typeof entry === "object" && !Array.isArray(entry)) {
                watchlist.push({ticker, ...entry});
            }
        }
    }

    elements.watchlistCount.textContent =
        `${watchlist.length} ${watchlist.length === 1 ? "ticker" : "tickers"}`;

    if (!watchlist.length) {
        elements.watchlistBody.innerHTML = `
            <tr>
                <td colspan="3" class="public-empty">
                    No watchlist entries available.
                </td>
            </tr>
        `;
        return;
    }

    const sortedWatchlist = [...watchlist].sort((a, b) =>
        String(a.ticker || "").localeCompare(String(b.ticker || ""))
    );

    elements.watchlistBody.innerHTML = sortedWatchlist.map((item) => {
        const ticker = escapeHtml(item.ticker || "—");

        const priceTargets = renderPriceTargets(
            item.price_targets ?? item.targets
        );

        const valuationTargets = renderValuationTargets(
            item.valuation_targets
        );

        return `
            <tr>
                <td>
                    <span class="public-ticker">${ticker}</span>
                </td>

                <td>${priceTargets}</td>

                <td>${valuationTargets}</td>
            </tr>
        `;
    }).join("");
}


/* -------------------------
   Data loading
------------------------- */

async function loadDashboard() {
    setLoading(true);
    showMessage("");

    const results = await Promise.allSettled([
        fetchJson(API.portfolio),
        fetchJson(API.watchlist),
    ]);

    const errors = [];

    if (results[0].status === "fulfilled") {
        cachedPortfolio = results[0].value;
        renderHoldings(cachedPortfolio);
    } else {
        console.error("Could not load public holdings:", results[0].reason);

        elements.holdingsBody.innerHTML = `
            <tr>
                <td colspan="6" class="public-empty">
                    Could not load holdings. Please try refreshing.
                </td>
            </tr>
        `;

        elements.holdingCount.textContent = "—";
        elements.allocationBasis.textContent = "—";
        errors.push("holdings");
    }

    if (results[1].status === "fulfilled") {
        cachedWatchlist = results[1].value;
        renderWatchlist(cachedWatchlist);
    } else {
        console.error("Could not load public watchlist:", results[1].reason);

        elements.watchlistBody.innerHTML = `
            <tr>
                <td colspan="3" class="public-empty">
                    Could not load watchlist. Please try refreshing.
                </td>
            </tr>
        `;

        elements.watchlistCount.textContent = "Unavailable";
        errors.push("watchlist");
    }

    if (errors.length) {
        showMessage(
            `Some data could not be loaded: ${errors.join(" and ")}. Please refresh to try again.`,
            true
        );
    } else {
        showMessage("");
    }

    setLoading(false);
}

elements.refreshButton.addEventListener("click", loadDashboard);


/* -------------------------
   Start dashboard
------------------------- */

activateTab("holdings");
loadDashboard();


/* -------------------------
   Analytics, read-only endpoints
------------------------- */
const PERFORMANCE_PERIODS = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "ALL"];
const GAINER_PERIODS = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"];
const analyticsCharts = {};
const analyticsRequests = new Map();
let performancePeriod = "1M";
let gainerPeriod = "1M";
const ALLOCATION_PERIOD = "1M"; // Fixed data source; independent of both chart selectors.
let lastAllocation = null;

const colors = ["#60a5fa", "#34d399", "#fbbf24", "#f472b6", "#a78bfa", "#fb923c",
    "#2dd4bf", "#818cf8", "#f87171", "#bef264", "#38bdf8", "#e879f9"];

function selector(id, periods, selected, callback) {
    const container = document.getElementById(id);
    container.replaceChildren();
    periods.forEach(period => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `analytics-period ${period === selected ? "active" : ""}`;
        button.textContent = period === "ALL" ? "All" : period;
        button.setAttribute("aria-pressed", String(period === selected));
        button.addEventListener("click", () => callback(period));
        container.appendChild(button);
    });
}

async function analyticsFor(period) {
    if (!analyticsRequests.has(period)) {
        const promise = fetchJson(`/api/public/analytics?period=${encodeURIComponent(period)}`)
            .catch(error => { analyticsRequests.delete(period); throw error; });
        analyticsRequests.set(period, promise);
    }
    return analyticsRequests.get(period);
}

function createChart(id, type, data, options = {}) {
    if (!window.Chart) {
        throw new Error("Chart.js could not be loaded. Check your connection to the chart library.");
    }
    if (analyticsCharts[id]) analyticsCharts[id].destroy();
    const element = document.getElementById(id);
    analyticsCharts[id] = new Chart(element, {
        type, data,
        options: {
            responsive: true, maintainAspectRatio: false,
            color: "#aaa",
            animation: { duration: 200 },
            plugins: { legend: { labels: { color: "#bbb", boxWidth: 12 } } },
            ...options,
        },
    });
}

async function updatePerformance() {
    const period = performancePeriod;
    const note = document.getElementById("performanceNote");
    note.textContent = "Loading market history…";
    try {
        const info = await analyticsFor(period);
        if (period !== performancePeriod) return;
        const spy = new Map(info.spy.map(p => [p.date, p.value]));
        const aligned = info.performance.filter(p => spy.has(p.date));
        if (aligned.length < 2) {
            if (analyticsCharts.performanceChart) analyticsCharts.performanceChart.destroy();
            delete analyticsCharts.performanceChart;
            note.textContent = "Not enough verified portfolio history for this period. " + info.performance_note;
            return;
        }
        createChart("performanceChart", "line", {
            labels: aligned.map(p => p.date),
            datasets: [
                { label: "Portfolio (proxy)", data: aligned.map(p => p.value), borderColor: "#60a5fa",
                  backgroundColor: "#60a5fa", borderWidth: 2.3, pointRadius: 0, tension: .15 },
                { label: "SPY", data: aligned.map(p => spy.get(p.date)), borderColor: "#bbb",
                  backgroundColor: "#bbb", borderWidth: 2, pointRadius: 0, tension: .15 },
            ],
        }, { interaction: { intersect: false, mode: "index" },
             scales: { x: { ticks: { maxTicksLimit: 7, color: "#888" }, grid: { display: false } },
                       y: { ticks: { color: "#888", callback: v => `${v}%` }, grid: { color: "#282828" } } },
             plugins: { legend: { labels: { color: "#bbb" } },
                        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}%` } } } });
        note.textContent = `${info.performance_note} Available from: ${String(info.available_from || "—").slice(0, 10)}.`;
    } catch (error) {
        note.textContent = `Performance unavailable: ${error.message}`;
    }
}

function doughnut(id, names, values) {
    if (!names.length) return;
    createChart(id, "doughnut", {
        labels: names,
        datasets: [{ data: values, backgroundColor: names.map((_, i) => colors[i % colors.length]),
                     borderColor: "#111", borderWidth: 2 }],
    }, { cutout: "65%", plugins: { legend: { position: "right", labels: { color: "#bbb", boxWidth: 10,
                   font: { size: 11 } } }, tooltip: { callbacks: { label: c => `${c.label}: ${c.parsed.toFixed(2)}%` } } } });
}

function updateAllocation(info) {
    if (info.holdings?.length) {
        elements.holdingCount.textContent = String(info.holdings.length);
        elements.allocationBasis.textContent = "Market value";
        renderHoldings({ positions: info.holdings, position_count: info.holdings.length,
                         allocation_basis: "Market value" });
        if (window.Chart) {
            doughnut("holdingsChart", info.holdings.map(h => h.ticker), info.holdings.map(h => h.allocation_pct));
            doughnut("sectorChart", info.sectors.map(h => h.sector), info.sectors.map(h => h.allocation_pct));
        }
    }
}

async function updateGainers() {
    const period = gainerPeriod;
    const note = document.getElementById("gainerNote");
    note.textContent = "Loading stock returns…";
    try {
        const info = await analyticsFor(period);
        if (period !== gainerPeriod) return;
        const sorted = [...info.gainers].sort((a, b) => b.return_pct - a.return_pct);
        if (!sorted.length) { note.textContent = "No price history available for the selected period."; return; }
        const shown = [...sorted.slice(0, 5), ...sorted.slice(-5).filter(x => !sorted.slice(0, 5).some(y => y.ticker === x.ticker))];
        createChart("gainersChart", "bar", {
            labels: shown.map(h => h.ticker),
            datasets: [{ label: "Price return", data: shown.map(h => h.return_pct),
                         backgroundColor: shown.map(h => h.return_pct >= 0 ? "#4ade80" : "#fb7185"),
                         borderRadius: 4 }],
        }, { indexAxis: "y", plugins: { legend: { display: false },
              tooltip: { callbacks: { label: c => `${c.parsed.x.toFixed(2)}%` } } },
              scales: { x: { ticks: { color: "#888", callback: v => `${v}%` }, grid: { color: "#282828" } },
                        y: { ticks: { color: "#bbb" }, grid: { display: false } } } });
        note.textContent = `Top and bottom performers by share-price return (${period}). ${info.missing_tickers?.length ? "Missing prices: " + info.missing_tickers.join(", ") + "." : ""}`;
    } catch (error) {
        note.textContent = `Gainers/losers unavailable: ${error.message}`;
    }
}

async function loadFixedAllocation() {
    try {
        // Always use the same snapshot source, regardless of either chart's period.
        const info = await analyticsFor(ALLOCATION_PERIOD);
        lastAllocation = info;
        updateAllocation(info);
    } catch (error) {
        console.error("Could not load fixed allocation:", error);
    }
}

function initializeAnalytics() {
    initializePerformanceSelector();
    initializeGainersSelector();
    loadFixedAllocation();
    updatePerformance();
    updateGainers();
}
function initializePerformanceSelector() {
    selector("performancePeriods", PERFORMANCE_PERIODS, performancePeriod, period => {
        performancePeriod = period; initializePerformanceSelector(); updatePerformance();
    });
}
function initializeGainersSelector() {
    selector("gainerPeriods", GAINER_PERIODS, gainerPeriod, period => {
        gainerPeriod = period; initializeGainersSelector(); updateGainers();
    });
}
// Refresh also clears short-lived browser request memoization.
elements.refreshButton.addEventListener("click", () => {
    analyticsRequests.clear();
    loadFixedAllocation();
    updatePerformance();
    updateGainers();
});

// Start charts after all analytics constants and functions are defined.
initializeAnalytics();
