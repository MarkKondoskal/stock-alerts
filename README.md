# 📈 Marks Portfolio & Market Monitor Pipeline

An automated GitHub Actions tracking pipeline for live stock price alerts, market sentiment monitoring, and portfolio management with Discord notifications.

---

## 📊 What We Are Monitoring

### 1. Stock Price Target Watchlist (`alerts/watchlist.json`)
Continuously tracks individual stock price targets using live `yfinance` market data during market hours.
* **Price Execution:** Triggers when a ticker's intraday low (`dayLow`) touches or breaches your specified target level.
* **Auto-Removal:** Once a target level is hit, an alert posts to Discord (`#stock-alerts`) and the target is automatically removed from `watchlist.json` via GitHub Actions bot.
* **International Support:** Supports international symbols using exchange suffixes (e.g., `ZAP.OL` for Zaptec ASA on Oslo Børs).

### 2. Market Sentiment & Volatility (`alerts/sentiment_alert.py`)
Monitors overall market health and risk sentiment, posting alerts directly to Discord (`#sentiment-alerts`):

* **CNN Fear & Greed Index:**
  Queries CNN's live sentiment engine to alert on market extreme conditions:
  * **Extreme Fear ($\le 25$):** Signals potential buying/oversold opportunities.
  * **Extreme Greed ($\ge 75$):** Signals heightened market euphoria or potential risk.

* **CBOE Volatility Index (VIX):**
  Monitors intraday spikes across key volatility thresholds (**12.0, 15.0, 25.0, 30.0, 35.0**).
  * Triggers when intraday VIX ranges cross key support or resistance levels to flag market turbulence.

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

* `DISCORD_STOCK_WEBHOOK` — Stock price target alert channel
* `DISCORD_SENTIMENT_WEBHOOK` — Market sentiment & VIX alert channel
* `DISCORD_PORTFOLIO_WEBHOOK` — Marks Portfolio updates channel

---

## 📂 Repository Structure

```text
stock-alerts/
│
├── .github/
│   └── workflows/
│       ├── stock_checker.yml        # Automated stock target & sentiment checker
│       └── portfolio_summary.yml    # Web-interactive portfolio management GUI
│
├── portfolio/
│   ├── marks_portfolio.json         # Live position holdings and buy prices
│   └── marks_portfolio_update.py    # Portfolio manager & pie chart generator
│
├── alerts/
│   ├── watchlist.json               # Stock price targets
│   ├── stock_alert.py               # Stock target checker
│   ├── sentiment_alert.py           # CNN Fear & Greed + VIX monitor
│   └── heartbeat.py                 # Status heartbeat monitor
│
└── README.md
```



