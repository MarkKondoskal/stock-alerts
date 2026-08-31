# 📈 Marks Portfolio & Market Monitor Pipeline

An automated GitHub Actions tracking pipeline for live stock price alerts, market sentiment monitoring, and portfolio management with Discord notifications.

---

## 📊 What We Are Monitoring

### 1. Stock Price Target Watchlist (`alerts/watchlist.json`)
Continuously tracks individual stock price targets using live `yfinance` market data during market hours.
* **Price Execution:** Triggers when a ticker's intraday low (`dayLow`) touches or breaches your specified target level.
* **Auto-Removal:** Once a target level is hit, an alert posts to Discord (`#stock-alerts`) and the target is automatically removed from `watchlist.json` via GitHub Actions bot.
* **International Support:** Supports international symbols using exchange suffixes (e.g., `ZAP.OL` for Zaptec ASA on Oslo Børs).

### 2. Watchlist Manager (GitHub UI)
You can now add/remove price targets directly from the GitHub Actions UI – no manual JSON editing.

**How to Use**
Go to the Actions tab.

Select Watchlist Manager from the left sidebar.

Click Run workflow.

Choose an action:

ADD – add a target price for a ticker (e.g., NVDA + 150.00).

REMOVE – remove a specific target.

REMOVE_ALL – remove all targets for a ticker.

LIST – print the current watchlist to the logs (no commit).

Fill in the required fields and run.

The changes are automatically committed and pushed – the next stock check will use the updated watchlist.

### 3. Market Sentiment & Volatility (`alerts/sentiment_alert.py`)
Monitors overall market health and risk sentiment, posting alerts directly to Discord (`#sentiment-alerts`):

* **CNN Fear & Greed Index:**
  Queries CNN's live sentiment engine to alert on market extreme conditions:
  * **Extreme Fear ($\le 25$):** Signals potential buying/oversold opportunities.
  * **Extreme Greed ($\ge 75$):** Signals heightened market euphoria or potential risk.

* **CBOE Volatility Index (VIX):**
  Monitors intraday spikes and drops across key thresholds using **directional hysteresis** to avoid duplicate alerts:
  * **Downward levels (10, 12, 15):** Alerts when VIX crosses *below* the level. After a first alert, a new alert for that level is only allowed after VIX has **risen above** `level + 2.0` (e.g., after crossing 15, VIX must first rise above 17 before another 15 alert can fire).
  * **Upward levels (25, 30, 35, 40, 45, 50):** Alerts when VIX crosses *above* the level. After an alert, a new alert requires VIX to **drop below** `level - 2.0` first (e.g., after crossing 25, VIX must fall below 23 to re‑arm).
  * Each level can alert **at most once per UTC day**, dramatically reducing noise while still capturing meaningful swings.

### 4. US Economic Data Monitor (alerts/economic_alert.py)
Fetches key US economic indicators from the FRED API (Federal Reserve) and posts updates to Discord (#sentiment-alerts) when new data is released.

Indicators tracked:

Unemployment Rate

CPI (All Urban Consumers)

GDP Growth Rate (quarter‑over‑quarter, annualised – shown as a percentage)

Core PCE Price Index

Nonfarm Payrolls

Initial Jobless Claims (weekly)

What you see in Discord:

Current value (formatted with % for rates/growth, whole numbers for payrolls/claims)

Previous value (for trend context)

Change with an up/down arrow (🟢 / 🔴 / ⚪)

Data source (FRED)

How it avoids spam: Stores the last date and value per series – only alerts when a new release or revision is detected.

Cost: Free – uses only the FRED API (no paid data sources).


---

## 🛠️ Portfolio Management Guide (GitHub Web GUI)

All portfolio holdings and buy prices are stored inside `portfolio/marks_portfolio.json`. You can manage your entire portfolio and push live updates directly from **GitHub.com** without running local terminal commands.

### How to Run Portfolio Actions via GitHub Web

1. Go to the **Actions** tab at the top of your GitHub repository.
2. In the left sidebar, click **Marks Portfolio Manager** (from `.github/workflows/portfolio_summary.yml`).
3. Click the **Run workflow** dropdown button on the right side.

---

### Available Modes in the Dropdown Form

#### Option A: Post Status Summary (`STATUS`)
* **Select Action:** `STATUS`
* **Ticker / Shares / Price:** Leave completely blank.
* **What Happens:** Queries live market prices for all holdings in `portfolio/marks_portfolio.json`, regenerates the donut allocation chart (showing position weights and individual returns without total dollar amounts), and posts the overview to `#marks-portfolio`.

#### Option B: Log a Buy Trade (`BUY`)
* **Select Action:** `BUY`
* **Ticker:** Enter symbol (e.g., `APP`, `AMZN`)
* **Shares:** Enter number of shares purchased (e.g., `5`)
* **Price:** Enter average fill price (e.g., `300.00`)
* **What Happens:** Recalculates position weights, regenerates the chart, posts a BUY notification to Discord, and automatically commits `portfolio/marks_portfolio.json` back to your GitHub repository.

#### Option C: Log a Sell Trade (`SELL`)
* **Select Action:** `SELL`
* **Ticker:** Enter symbol (e.g., `META`)
* **Shares:** Enter number of shares sold (e.g., `2`)
* **Price:** Enter execution price (e.g., `525.00`)
* **What Happens:** Adjusts share count, updates remaining position weights, posts a SELL notification to Discord, and commits changes back to your repository.

---

## ⚙️ Environment Secrets

Required GitHub Repository Secrets (`Settings` → `Secrets and variables` → `Actions`):

| Secret Name | Purpose |
|-------------|---------|
| `DISCORD_STOCK_WEBHOOK` | Stock price target alert channel |
| `DISCORD_SENTIMENT_WEBHOOK` | Market sentiment & VIX alert channel |
| `DISCORD_PORTFOLIO_WEBHOOK` | Marks Portfolio updates channel |
| `DISCORD_PORTFOLIO_TEST_WEBHOOK | Heartbeat monitor channel – used by `alerts/heartbeat.py` |

---

## 📂 Repository Structure

```text
stock-alerts/
│
├── .github/
│   └── workflows/
│       ├── stock_checker.yml        # Runs every 15 min, 07:00-21:00 UTC, Mon-Fri
│       ├── portfolio_summary.yml    # Portfolio management (STATUS, BUY, SELL)
│       └── watchlist_manager.yml    # Add/remove watchlist targets via UI
│
├── portfolio/
│   ├── marks_portfolio.json         # Live holdings, transactions, realised P&L
│   └── marks_portfolio_update.py    # Portfolio manager & pie chart generator
│
├── alerts/
│   ├── watchlist.json               # Stock price targets
│   ├── stock_alert.py               # Checks targets, posts alerts, auto-removes
│   ├── sentiment_alert.py           # CNN Fear & Greed + VIX monitor with hysteresis
│   ├── sentiment_state.json         # Persistent VIX & Fear/Greed state (auto‑committed)
│   └── heartbeat.py                 # Daily system heartbeat (scheduled at 14:30 UTC)
│
└── README.md
