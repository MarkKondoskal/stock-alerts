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

## 🛠️ Portfolio Management Guide (Marks Portfolio)

All portfolio holdings and buy prices are stored inside `portfolio/portfolio.json`. 

### Adding or Updating a Position
To log a trade and automatically send an updated donut allocation chart to Discord, run the following command in your terminal:

```bash
# Command format:
python portfolio/Marks_portfolio_updates.py [ACTION] [TICKER] [SHARES] [PRICE]

# Examples:
python portfolio/Marks_portfolio_updates.py BUY APP 5 300.00
python portfolio/Marks_portfolio_updates.py BUY AMZN 10 180.50
python portfolio/Marks_portfolio_updates.py SELL META 2 525.00
