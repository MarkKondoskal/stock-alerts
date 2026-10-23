# Stock Alerts & Watchlist Bot

A GitHub Actions-powered stock monitoring project that sends price-target and valuation alerts to Discord, publishes a compact watchlist table, and runs the project's other market, sentiment, earnings, and portfolio workflows.

## Watchlist features

- Price targets: alert when the intraday low reaches or falls below a target price.
- Valuation targets using **Forward P/E (`FxPE`)**, **trailing P/E (`PE`)**, and **Price/Sales (`P/S`)**.
- Two directions for every valuation metric:
  - **TRIM**: alert when the valuation multiple is **at or above** the target (for example, MA Forward P/E ≥ 35x).
  - **BUY**: alert when the valuation multiple is **at or below** the target (for example, MA Forward P/E ≤ 25x).
- A ticker can have multiple price targets and multiple buy/trim valuation targets at the same time.
- Missing valuation data does not trigger an alert or remove the target.
- Targets are removed only after Discord accepts the alert. If delivery fails, the target remains for a later retry.
- The Discord status post shows current price, price targets, PE, forward PE, P/S, and year-over-year revenue growth in a compact table. All tickers are included in one webhook message, split into continuation embeds only if Discord's message-size limits require it.

## How valuation alerts work

The scanner uses Yahoo Finance/yfinance fundamentals. A **TRIM** target is triggered when the reported multiple is greater than or equal to the configured threshold. A **BUY** target is triggered when the reported multiple is less than or equal to the threshold. A valuation alert is based on the latest available fundamental data, which may update less frequently than the stock price. It is not a guarantee that the multiple or share price is real-time.

## GitHub setup

1. Push the repository to GitHub.
2. Open **Settings → Secrets and variables → Actions**.
3. Add the Discord webhook secrets used by the workflows in this repository. For the stock alert scanner, set `DISCORD_STOCK_WEBHOOK`. The watchlist manager accepts `DISCORD_WATCHLIST_WEBHOOK` or falls back to `DISCORD_STOCK_WEBHOOK`.
4. Ensure GitHub Actions has permission to commit changes to `alerts/watchlist.json` (the workflow uses repository contents write permission).
5. Run workflows manually once to confirm the secrets and permissions are correct.

Never commit webhook URLs or other credentials directly into source files.

## Add a target

Open **Actions → Watchlist Manager → Run workflow**.

Inputs:

- **Action**: `ADD`
- **Ticker**: ticker symbol such as `MA`
- **Target**: numeric share price or valuation multiple (enter `35`, not `35x`)
- **Metric**: `PRICE`, `FxPE`, `PE`, or `P/S`
- **Direction**: `TRIM` or `BUY`. Direction is relevant to valuation metrics; for `PRICE`, the existing behavior is a downside price target.

Examples:

| Goal | Metric | Target | Direction | Meaning |
|---|---|---:|---|---|
| Mastercard trim zone | `FxPE` | `35` | `TRIM` | Alert at forward P/E ≥ 35x |
| Mastercard buy zone | `FxPE` | `25` | `BUY` | Alert at forward P/E ≤ 25x |
| Buy-zone price alert | `PRICE` | `300` | `TRIM` (ignored for price) | Alert when price reaches $300 or lower |
| High trailing P/E alert | `PE` | `40` | `TRIM` | Alert at trailing P/E ≥ 40x |
| Low price-to-sales buy zone | `P/S` | `5` | `BUY` | Alert at P/S ≤ 5x |

For valuation metrics, “TRIM” and “BUY” describe the valuation condition, not an automatic trade. The bot only sends a notification; it does not place trades.

## Remove targets

Use the same **Metric**, **Target**, and **Direction** inputs with action `REMOVE`. Direction must match the target being removed. Use `REMOVE_ALL` to remove all targets for a ticker. `LIST` prints stored targets to the workflow log; `STATUS` posts the current watchlist to Discord.

## Watchlist data format

The data lives in `alerts/watchlist.json`. The manager migrates older valuation lists as trim targets for backward compatibility. New valuation targets use this structure:

```json
{
  "MA": {
    "price_targets": [300.0],
    "valuation_targets": {
      "FxPE": {
        "trim": [35.0],
        "buy": [25.0]
      },
      "P/S": {
        "trim": [],
        "buy": [5.0]
      }
    }
  }
}
```

The watchlist manager commits changes to `alerts/watchlist.json` when run through GitHub Actions. Avoid editing the file at the same time as a workflow run.

## Workflows

Workflow definitions are in `.github/workflows/`. Open the **Actions** tab to see each workflow and its schedule. The stock alert pipeline checks active price and valuation targets; the watchlist manager adds/removes targets and publishes the Discord table. Other workflows handle the project's earnings, economic, sentiment, heartbeat, and portfolio reporting tasks.

## Local testing

Install Python 3.11 and dependencies:

```bash
pip install requests yfinance
```

Run the watchlist manager from the repository root:

```bash
python alerts/watchlist_manager.py LIST
python alerts/watchlist_manager.py STATUS
python alerts/watchlist_manager.py ADD MA 35 FxPE TRIM
python alerts/watchlist_manager.py ADD MA 25 FxPE BUY
python alerts/watchlist_manager.py REMOVE MA 35 FxPE TRIM
```

The `STATUS` action needs a valid Discord webhook environment variable. The stock scanner requires `DISCORD_STOCK_WEBHOOK`.

## Troubleshooting

- **No Discord message:** check the relevant webhook secret and the GitHub Actions logs.
- **Workflow cannot push changes:** check repository Actions permissions and branch protection rules.
- **No valuation alert:** confirm the ticker has a target, the selected metric is available from Yahoo Finance, and the multiple has crossed the threshold in the correct direction.
- **Valuation shown as `—`:** Yahoo Finance may not provide that multiple for the ticker. Missing data is kept as unavailable rather than treated as zero.
- **Unexpected valuation:** provider fundamentals can be delayed, revised, or calculated differently by data vendors. Confirm important decisions independently.
- **Duplicate alert after an uncertain network failure:** if Discord accepted a message but the connection failed before the workflow received confirmation, a retry can potentially send it again. The bot does not execute trades.

## Disclaimer

This project is for personal monitoring and informational purposes only, not financial advice. Data may be delayed or inaccurate. Alerts are notifications, not buy/sell orders; independently verify data and make your own investment decisions.
## Web dashboard (new)

A responsive dashboard is available in [`web/`](web/README.md). It reads the actual portfolio/watchlist files from this repository, saves watchlist edits back through the GitHub API, displays real GitHub Actions run history, and can send a server-side Discord webhook test. The dashboard does not replace the Python alert engine or scheduled workflows.

See [`web/README.md`](web/README.md) for local setup, required environment variables, GitHub token permissions, and deployment notes. Never commit tokens, passwords, or Discord webhook URLs.
