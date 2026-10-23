# StockAlerts Core web dashboard

This folder adds a small web UI to the existing `stock-alerts-main` repository. The Python alert scripts and scheduled GitHub Actions remain the source of truth. The dashboard reads/writes the real `alerts/watchlist.json` and reads the real `portfolio/marks_portfolio.json` and GitHub Actions run history.

## Current capabilities

- Dark, responsive dashboard inspired by the supplied UI reference.
- Portfolio holdings and recorded cost basis from the repository JSON. It does **not** pretend cost basis is live market value.
- Watchlist target editor for price, forward P/E (`FxPE`), trailing P/E (`PE`) and price/sales (`P/S`), including BUY/ TRIM valuation directions.
- Saves watchlist edits by creating a commit through GitHub's Contents API.
- Shows actual workflow runs and can dispatch the listed workflows, except Watchlist Manager through the generic button because that workflow requires inputs.
- Sends a Discord test message using a server-side webhook secret.

Live quote values, the exact existing Discord embed preview, and economic/sentiment live data are not fabricated. They should be added by consuming actual project output or a chosen quote provider in a later pass.

## Run locally

Requires Python 3.11+.

```bash
cd web
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variables before starting:

```powershell
$env:DASHBOARD_PASSWORD="a-long-unique-password"
$env:GITHUB_TOKEN="github_fine_grained_token"
$env:GITHUB_REPOSITORY="YOUR_USERNAME/stock-alerts-main"
$env:GITHUB_BRANCH="main"
$env:DISCORD_STOCK_WEBHOOK="your_webhook_url"
python app.py
```

Then open `http://127.0.0.1:8000`. Use the dashboard password to connect. For local testing, keep it bound to localhost. Do not commit `.env` files, tokens, passwords, or webhook URLs.

## GitHub token permissions

Use a fine-grained token limited to this repository. Grant **Contents: Read and write** (for updating `alerts/watchlist.json`) and **Actions: Read and write** (for reading runs and dispatching workflows). Do not use a token with broad account access if a repository-scoped token will work.

## Deployment

This is not a GitHub Pages-only app: editing files and dispatching workflows require a server-side API. Deploy the repository to a Python-capable host with a WSGI server (the included `Procfile` uses Gunicorn), then configure the environment variables in the host's secret settings. Use HTTPS. Set `GITHUB_REPOSITORY` as `owner/repo`, not a URL. Keep the dashboard password and all tokens/webhooks in the host's environment/secret manager.

The dashboard currently uses a simple shared password for access. Use a strong unique password and deploy only behind HTTPS; if you later expose this publicly, add proper user authentication/rate limiting before opening access broadly.

## API endpoints

- `GET /api/health` — non-secret service configuration status.
- `GET /api/watchlist` and `PUT /api/watchlist` — read/update repository watchlist.
- `GET /api/portfolio` — read portfolio JSON and cost basis.
- `GET /api/workflows` — recent Actions runs.
- `POST /api/workflows/dispatch` — dispatch allowlisted workflows.
- `POST /api/discord/test` — send a real test using `DISCORD_STOCK_WEBHOOK`.
