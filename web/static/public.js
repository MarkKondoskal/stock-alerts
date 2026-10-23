
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
    const holdings = asArray(payload, [
        "holdings",
        "portfolio",
        "positions",
        "data",
    ]);

    // Some API responses may wrap the holdings in an object.
    const metadata = payload && !Array.isArray(payload)
        ? payload
        : {};

    elements.holdingCount.textContent = String(
        metadata.position_count ?? holdings.length
    );

    elements.allocationBasis.textContent =
        metadata.allocation_basis || "Cost basis";

    if (!holdings.length) {
        elements.holdingsBody.innerHTML = `
            <tr>
                <td colspan="3" class="public-empty">
                    No holdings available.
                </td>
            </tr>
        `;
        return;
    }

    const sortedHoldings = [...holdings].sort((a, b) =>
        String(a.ticker || "").localeCompare(String(b.ticker || ""))
    );

    elements.holdingsBody.innerHTML = sortedHoldings.map((holding) => {
        const ticker = escapeHtml(holding.ticker || "—");

        const avgPrice = Number(
            holding.avg_price ?? holding.average_price
        );

        const allocation = Number(
            holding.allocation_pct ?? holding.allocation
        );

        const safeAllocation = Number.isFinite(allocation)
            ? Math.max(0, Math.min(100, allocation))
            : 0;

        const allocationText = Number.isFinite(allocation)
            ? `${formatNumber(allocation, 2)}%`
            : "—";

        return `
            <tr>
                <td>
                    <span class="public-ticker">${ticker}</span>
                </td>

                <td class="public-number">
                    ${formatPrice(avgPrice)}
                </td>

                <td>
                    <div class="public-allocation">
                        <span class="public-number">
                            ${allocationText}
                        </span>

                        <div class="public-allocation-track"
                             aria-hidden="true">
                            <div
                                class="public-allocation-fill"
                                style="width: ${safeAllocation}%;">
                            </div>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
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
    if (!targets) {
        return renderTargetChips([]);
    }

    const entries = Array.isArray(targets)
        ? targets.map((target) => [
            target.metric || target.type || "Valuation",
            target,
        ])
        : Object.entries(targets);

    const chips = [];

    for (const [metric, target] of entries) {
        if (target === null || target === undefined || target === "") {
            continue;
        }

        let label = String(metric);
        let value = target;

        if (target && typeof target === "object") {
            label = target.metric || target.type || label;
            value = target.multiple ?? target.value ?? target.target ?? target;

            const direction = target.direction || target.action || "";
            const formattedValue = formatTargetValue(value);

            chips.push({
                label,
                value: direction
                    ? `${direction} ${formattedValue}`
                    : formattedValue,
            });
        } else {
            chips.push({
                label,
                value: formatTargetValue(value),
            });
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
        "watchlist",
        "items",
        "data",
    ]);

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
                <td colspan="3" class="public-empty">
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
