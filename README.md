# Marks Portfolio & Market Monitor

A Python automation project that monitors stock price targets and valuation multiples, posts alerts and a compact watchlist to Discord, tracks portfolio transactions and earnings, and checks selected market/economic indicators. GitHub Actions runs the scheduled workflows, so a personal computer does not need to stay on.

> Market data comes from Yahoo Finance through `yfinance` and may be missing, delayed, or revised. Alerts are notifications, not trade execution or financial advice.

## Contents

- [Features](#features)
- [Price and valuation alerts](#price-and-valuation-alerts)
- [Discord watchlist](#discord-watchlist)
- [Manage watchlist targets](#manage-watchlist-targets)
- [GitHub setup](#github-setup)
- [Workflows](#workflows)
- [Portfolio and other monitors](#portfolio-and-other-monitors)
- [Run locally](#run-locally)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

## Features

- Multiple price targets per ticker.
- Valuation alerts for trailing P/E (`PE`), forward P/E (`FxPE`), and price-to-sales (`P/S`).
- Discord watchlist with price, targets, valuation metrics, and year-over-year revenue growth.
- Portfolio BUY/SELL transaction updates and portfolio summaries.
- Earnings report workflow for tracked portfolio holdings.
- Market sentiment/VIX, selected US economic data, and workflow heartbeat notifications.
- JSON-based configuration and state committed to the repository by GitHub Actions.

## Price and valuation alerts

The watchlist is stored in `alerts/watchlist.json`. A ticker can have price targets, valuation targets, or both. Example:

```json
{
  "MA": {
    "price_targets": [],
    "valuation_targets": {
      "FxPE": [35]
    }
  }
}
```

Supported metrics:

| Metric | Data field | Trigger rule |
|---|---|---|
| `PRICE` | Intraday low when available; otherwise latest price | Alert when price is at or below target |
| `PE` | Yahoo Finance `trailingPE` | Alert when the multiple is at or above target |
| `FxPE` | Yahoo Finance `forwardPE` | Alert when the multiple is at or above target |
| `P/S` | Yahoo Finance `priceToSalesTrailing12Months` | Alert when the multiple is at or above target |

For example, `FxPE = 35` means an alert when forward P/E is 35x or higher. The monitor can alert on its next run if the multiple is already above the target; it does not need to observe the exact moment the multiple crosses the threshold.

**Delivery safeguards:** a triggered target is removed only after Discord returns HTTP 200 or 204. If the webhook fails, or the relevant data is unavailable, the target remains in the watchlist for a later attempt. Targets are handled individually, so a successful alert does not remove unrelated targets for the same ticker.

Valuation checks only run for tickers with valuation targets, helping limit requests to Yahoo Finance. The display in the Watchlist Manager separately retrieves the latest available multiples for all listed tickers.

## Discord watchlist

The Watchlist Manager's `STATUS` action posts the watchlist as one Discord message/table, not a separate message per ticker. Columns include:

- **Ticker** and **Price**
- **Targets** — configured price targets and valuation target thresholds
- **PE** — trailing price-to-earnings
- **FwdPE** — forward price-to-earnings
- **P/S** — trailing price-to-sales
- **Rev YoY** — year-over-year revenue growth, when supplied by Yahoo Finance

A `—` means the provider did not return a usable value; it does not mean zero. `Rev YoY` is shown as a percentage and can be negative. Long tables may require horizontal scrolling on narrow Discord clients, but all tickers remain in the same table/post where Discord message limits permit.

## Manage watchlist targets

### GitHub Actions UI

1. Open the repository's **Actions** tab.
2. Select **Watchlist Manager**.
3. Click **Run workflow**.
4. Select the action and enter the ticker, target, and metric requested by the workflow form.
5. Run `STATUS` to post the full watchlist to Discord.

The workflow form is the recommended way to manage targets. The supported metric identifiers are `PRICE`, `PE`, `FxPE`, and `P/S`; use the exact metric label offered by the workflow.

### Command line

From the repository root, install dependencies first, then use examples like:

```bash
# Add a price target
python alerts/watchlist_manager.py ADD AMD 560 PRICE

# Add a forward P/E target for Mastercard
python alerts/watchlist_manager.py ADD MA 35 FxPE

# Add trailing P/E or price-to-sales thresholds
python alerts/watchlist_manager.py ADD MSFT 40 PE
python alerts/watchlist_manager.py ADD AMZN 5 'P/S'

# Remove a specific target
python alerts/watchlist_manager.py REMOVE MA 35 FxPE

# List stored targets or post the full watchlist
python alerts/watchlist_manager.py LIST
python alerts/watchlist_manager.py STATUS
```

Check `python alerts/watchlist_manager.py --help` or the script's argument parser if your checked-out version exposes different CLI syntax. Do not manually edit JSON while a workflow that writes the same file is running.

## GitHub setup

### Repository secrets

Add secrets under **Settings → Secrets and variables → Actions**. Use the exact names referenced by each workflow file. The stock monitor expects:

- `DISCORD_STOCK_WEBHOOK` — Discord webhook for price and valuation alerts.
- `DISCORD_SENTIMENT_WEBHOOK` — webhook for market sentiment alerts.

Other workflows may require additional webhook or data-provider secrets; inspect the `env:` sections of the corresponding YAML files and add only the secrets they reference. Never commit webhook URLs or API keys to the repository.

### Permissions

Workflows that commit JSON state need repository Actions permissions that allow content writes. Under **Settings → Actions → General → Workflow permissions**, enable read and write permissions if required by your repository policy. Branch protection rules may also affect automated pushes.

## Workflows

Workflow schedules and names can change; the YAML files under `.github/workflows/` are the source of truth. In the uploaded project, the principal workflows include:

| Workflow file | Purpose |
|---|---|
| `stock_checker.yml` | Scheduled price and valuation scanning plus sentiment monitoring; commits changed watchlist/sentiment state |
| `watchlist_manager.yml` | Manually manage targets and post the current watchlist |
| `portfolio_summary.yml` | Manually run portfolio status and transaction actions |
| `earnings_report.yml` | Generate earnings reports for tracked holdings |
| `economic_alert.yml` | Monitor selected US economic releases and Fed updates |
| `heartbeat.yml` | Send a scheduled heartbeat message |

GitHub Actions scheduled workflows may run later than the exact cron time during periods of high load. Check the latest workflow run and its logs when troubleshooting.

## Portfolio and other monitors

- **Portfolio manager:** uses `portfolio/marks_portfolio.json` and `portfolio/marks_portfolio_update.py` for portfolio status and BUY/SELL actions. Review transaction and cost-basis behavior before relying on reported performance.
- **Earnings reports:** `portfolio/earnings_report.py` produces earnings-related updates for tracked holdings. Availability and estimates depend on the upstream data source.
- **Market sentiment:** `alerts/sentiment_alert.py` checks configured sentiment/VIX conditions and records state in `alerts/sentiment_state.json`.
- **Economic monitor:** `alerts/economic_alert.py` checks configured economic/Federal Reserve data and uses `alerts/economic_state.json` to track state.
- **Heartbeat:** `alerts/heartbeat.py` sends a basic scheduled workflow notification.

The project sends notifications and updates its local JSON ledger. It does not connect to a brokerage, submit orders, or guarantee execution prices.

## Run locally

Requires Python 3.11 or a compatible version and internet access for Yahoo Finance/Discord requests.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install requests yfinance
```

Set the relevant environment variables before running any script that posts to Discord. For example, in PowerShell for the current terminal session:

```powershell
$env:DISCORD_STOCK_WEBHOOK = "your-webhook-url"
python alerts/stock_alert.py
```

Run `python alerts/watchlist_manager.py STATUS` to post the watchlist. Keep webhook URLs private and avoid including them in screenshots or logs shared publicly.

## Troubleshooting

### A price target did not alert

1. Open **Actions → Stock & Sentiment Alert Pipeline** and inspect the latest run logs.
2. Confirm the ticker and target exist in `alerts/watchlist.json`.
3. Confirm `DISCORD_STOCK_WEBHOOK` is configured and points to the intended channel.
4. Remember that price alerts use the intraday low when available; otherwise the latest price is used.

### A valuation target did not alert

1. Confirm the ticker has a target under `valuation_targets` and the metric key is exactly `PE`, `FxPE`, or `P/S`.
2. Confirm Yahoo Finance provides a positive value for the corresponding field (`trailingPE`, `forwardPE`, or `priceToSalesTrailing12Months`).
3. Valuation alerts trigger at-or-above the threshold; price alerts trigger at-or-below the target.
4. Check the workflow logs for provider or Discord errors. Missing data does not trigger an alert and does not delete the target.

### A valuation or revenue-growth cell displays `—`

Yahoo Finance may not provide that field for a particular ticker or response. The project treats unavailable data as missing, not as zero.

### A ticker's price is `N/A`

Check the ticker symbol and exchange suffix. International symbols (for example, `.OL`) may not resolve consistently through Yahoo Finance.

### Discord did not receive a message

Verify the relevant secret name and webhook URL, inspect the step logs, and run the Watchlist Manager `STATUS` action to test the watchlist webhook path. A successful HTTP response means Discord accepted the webhook request; it does not verify how the client displayed the message.

### GitHub Actions cannot commit JSON changes

Check workflow permissions, branch protection, and whether another workflow is writing to the same file. Resolve push conflicts before rerunning.

## Project structure

```text
stock-alerts-main/
├── .github/workflows/       # GitHub Actions schedules and manual workflows
├── alerts/
│   ├── stock_alert.py       # Price and valuation alert scanner
│   ├── watchlist_manager.py # Watchlist targets and Discord table
│   ├── watchlist.json       # Watchlist targets
│   ├── sentiment_alert.py   # Sentiment/VIX monitor
│   ├── sentiment_state.json # Sentiment state
│   ├── economic_alert.py    # Economic data monitor
│   ├── economic_state.json # Economic monitor state
│   └── heartbeat.py         # Workflow heartbeat
└── portfolio/
    ├── marks_portfolio.json
    ├── marks_portfolio_update.py
    └── earnings_report.py
```

---

*Use the alerts as monitoring aids only. Verify the underlying data and make investment decisions independently.*
