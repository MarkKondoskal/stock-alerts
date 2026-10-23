
"""Server-side bridge between the dashboard and GitHub/Discord.

Code and GitHub Actions live in GITHUB_REPOSITORY.
Private portfolio/watchlist JSON files live in GITHUB_DATA_REPOSITORY.

Never expose GitHub tokens or Discord webhooks in browser code.
"""
import base64
import json
import os
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

# Load web/.env locally. Environment variables supplied by the host take precedence.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
API = "https://api.github.com"


def config():
    """Read configuration from environment variables."""
    return {
        "token": os.getenv("GITHUB_TOKEN", "").strip(),
        "repo": os.getenv("GITHUB_REPOSITORY", "").strip(),
        "branch": os.getenv("GITHUB_BRANCH", "main").strip() or "main",
        "password": os.getenv("DASHBOARD_PASSWORD", "").strip(),
        "data_repo": os.getenv("GITHUB_DATA_REPOSITORY", "").strip(),
        "data_branch": os.getenv("GITHUB_DATA_BRANCH", "main").strip() or "main",
    }


def require_auth():
    """Authenticate dashboard API requests and validate required settings."""
    cfg = config()

    if not cfg["password"]:
        return jsonify({
            "error": "Server setup error: DASHBOARD_PASSWORD is not configured."
        }), 503

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != cfg["password"]:
        return jsonify({
            "error": "Unauthorized. Enter your dashboard password."
        }), 401

    if not cfg["token"] or not cfg["repo"]:
        return jsonify({
            "error": "Server setup error: GITHUB_TOKEN and GITHUB_REPOSITORY are required."
        }), 503

    if not cfg["data_repo"]:
        return jsonify({
            "error": "Server setup error: GITHUB_DATA_REPOSITORY is not configured."
        }), 503

    return None


def gh_headers():
    """Headers used for authenticated GitHub API calls."""
    token = config()["token"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def repository_and_branch(data=False):
    """Return the selected repository and branch."""
    cfg = config()

    if data:
        repository = cfg["data_repo"]
        branch = cfg["data_branch"]
        label = "Private data repository"
    else:
        repository = cfg["repo"]
        branch = cfg["branch"]
        label = "Code repository"

    if not repository:
        raise RuntimeError(f"{label} is not configured.")

    # Prevent malformed repository names from entering API URLs.
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise RuntimeError(
            f"{label} must be configured as OWNER/REPOSITORY."
        )

    return repository, branch


def repo_url(path, data=False):
    """Build a GitHub Contents API URL for a file."""
    repository, branch = repository_and_branch(data=data)
    safe_path = quote(path.strip("/"), safe="/")
    safe_branch = quote(branch, safe="")

    return (
        f"{API}/repos/{repository}/contents/{safe_path}"
        f"?ref={safe_branch}"
    )


def api_repo_url(path, data=False):
    """Build a GitHub repository API URL, e.g. Actions endpoints."""
    repository, _ = repository_and_branch(data=data)
    safe_path = path.strip("/")
    return f"{API}/repos/{repository}/{safe_path}"


def get_file(path, data=False):
    """Read and decode a JSON file from the selected repository."""
    response = requests.get(
        repo_url(path, data=data),
        headers=gh_headers(),
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    if "content" not in payload or "sha" not in payload:
        raise ValueError(f"GitHub did not return file content for {path}.")

    raw = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(raw), payload["sha"]


def put_file(path, content, message, data=False):
    """Update an existing JSON file and commit it to the selected repository."""
    _, branch = repository_and_branch(data=data)
    url = repo_url(path, data=data)

    # GitHub requires the current SHA when updating an existing file.
    current_response = requests.get(
        url,
        headers=gh_headers(),
        timeout=20,
    )
    current_response.raise_for_status()
    current_file = current_response.json()

    raw = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    payload = {
        "message": message,
        "content": encoded,
        "sha": current_file["sha"],
        "branch": branch,
    }

    response = requests.put(
        url,
        headers=gh_headers(),
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    cfg = config()
    return jsonify({
        "service": "stock-alerts-dashboard",
        "configured": bool(
            cfg["password"]
            and cfg["token"]
            and cfg["repo"]
            and cfg["data_repo"]
        ),
        "code_repository_configured": bool(cfg["repo"]),
        "private_data_repository_configured": bool(cfg["data_repo"]),
        "github_token_configured": bool(cfg["token"]),
        "dashboard_password_configured": bool(cfg["password"]),
    })


@app.get("/api/watchlist")
def watchlist_get():
    err = require_auth()
    if err:
        return err

    try:
        watchlist, _ = get_file("alerts/watchlist.json", data=True)
        if not isinstance(watchlist, dict):
            return jsonify({
                "error": "Watchlist file must contain a JSON object."
            }), 502
        return jsonify(watchlist)

    except requests.RequestException:
        app.logger.exception("GitHub request failed while reading watchlist")
        return jsonify({
            "error": "Could not read watchlist from the private GitHub repository. "
                     "Check the token permissions, repository, branch, and file path."
        }), 502
    except (ValueError, KeyError, TypeError, RuntimeError):
        app.logger.exception("Could not parse or locate the watchlist")
        return jsonify({
            "error": "Could not parse or locate the private watchlist. "
                     "Check the server log for details."
        }), 502


@app.put("/api/watchlist")
def watchlist_put():
    err = require_auth()
    if err:
        return err

    incoming = request.get_json(silent=True)
    if not isinstance(incoming, dict):
        return jsonify({
            "error": "Expected watchlist JSON object."
        }), 400

    cleaned = {}

    for raw_ticker, item in incoming.items():
        ticker = str(raw_ticker).strip().upper()

        if not ticker or not isinstance(item, dict):
            return jsonify({
                "error": "Each watchlist entry must be an object with a ticker."
            }), 400

        prices = item.get("price_targets", [])
        vals = item.get("valuation_targets", {})

        if not isinstance(prices, list) or not isinstance(vals, dict):
            return jsonify({
                "error": f"Invalid target format for {ticker}."
            }), 400

        try:
            price_targets = [
                float(value) for value in prices if str(value).strip()
            ]

            valuation_targets = {}

            for metric, directions in vals.items():
                if metric not in ("FxPE", "PE", "P/S"):
                    continue
                if not isinstance(directions, dict):
                    raise ValueError(
                        f"{ticker} {metric} targets must be an object."
                    )

                metric_targets = {}

                for direction in ("trim", "buy"):
                    values = directions.get(direction, [])

                    if not isinstance(values, list):
                        raise ValueError(
                            f"{ticker} {metric} {direction} must be a list."
                        )

                    metric_targets[direction] = [
                        float(value)
                        for value in values
                        if str(value).strip()
                    ]

                valuation_targets[metric] = metric_targets

            cleaned[ticker] = {
                "price_targets": price_targets,
                "valuation_targets": valuation_targets,
            }

        except (ValueError, TypeError) as exc:
            return jsonify({
                "error": f"Invalid numeric target: {exc}"
            }), 400

    try:
        result = put_file(
            "alerts/watchlist.json",
            cleaned,
            "Update watchlist from web dashboard",
            data=True,
        )

        return jsonify({
            "ok": True,
            "message": "Watchlist saved to the private data repository.",
            "commit": result.get("commit", {}).get("sha"),
        })

    except requests.RequestException:
        app.logger.exception("GitHub request failed while saving watchlist")
        return jsonify({
            "error": "Could not save the watchlist to the private GitHub repository. "
                     "Check token write permissions and the server log."
        }), 502
    except (ValueError, KeyError, TypeError, RuntimeError):
        app.logger.exception("Could not save the watchlist")
        return jsonify({
            "error": "Could not save the watchlist. Check the server log for details."
        }), 502


@app.get("/api/portfolio")
def portfolio_get():
    err = require_auth()
    if err:
        return err

    try:
        portfolio, _ = get_file(
            "portfolio/marks_portfolio.json",
            data=True,
        )

        if not isinstance(portfolio, dict):
            return jsonify({
                "error": "Portfolio file must contain a JSON object."
            }), 502

        positions = []
        total_cost = 0.0

        for ticker, item in portfolio.items():
            if ticker == "closed_positions" or not isinstance(item, dict):
                continue

            shares = float(item.get("shares", 0) or 0)
            avg_price = float(item.get("avg_price", 0) or 0)
            cost_basis = shares * avg_price
            realized_pl = float(item.get("realized_pl", 0) or 0)

            total_cost += cost_basis
            positions.append({
                "ticker": ticker,
                "shares": shares,
                "avg_price": avg_price,
                "cost_basis": cost_basis,
                "realized_pl": realized_pl,
            })

        positions.sort(key=lambda position: position["cost_basis"], reverse=True)

        return jsonify({
            "positions": positions,
            "position_count": len(positions),
            "total_cost_basis": total_cost,
            "note": (
                "Cost basis from private repository. Live market value is not "
                "shown unless a live quote source is configured."
            ),
        })

    except requests.RequestException:
        app.logger.exception("GitHub request failed while reading portfolio")
        return jsonify({
            "error": "Could not read the portfolio from the private GitHub repository. "
                     "Check token permissions, repository, branch, and file path."
        }), 502
    except (ValueError, KeyError, TypeError, RuntimeError):
        app.logger.exception("Could not parse or locate the portfolio")
        return jsonify({
            "error": "Could not parse or locate the private portfolio. "
                     "Check the server log for details."
        }), 502


@app.get("/api/workflows")
def workflows_get():
    err = require_auth()
    if err:
        return err

    cfg = config()

    try:
        response = requests.get(
            api_repo_url("actions/runs"),
            headers=gh_headers(),
            params={
                "branch": cfg["branch"],
                "per_page": 15,
            },
            timeout=20,
        )

        if not response.ok:
            app.logger.error(
                "GitHub Actions history request failed: %s %s",
                response.status_code,
                response.text[:300],
            )
            return jsonify({
                "error": f"GitHub Actions API error ({response.status_code}). "
                         "Check token permissions."
            }), response.status_code

        runs = []
        for item in response.json().get("workflow_runs", []):
            runs.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "event": item.get("event"),
                "created_at": item.get("created_at"),
                "html_url": item.get("html_url"),
                "path": item.get("path"),
            })

        return jsonify(runs)

    except requests.RequestException:
        app.logger.exception("GitHub request failed while loading workflows")
        return jsonify({
            "error": "Could not load GitHub Actions history."
        }), 502
    except (ValueError, RuntimeError):
        app.logger.exception("Could not process workflow history")
        return jsonify({
            "error": "Could not process GitHub Actions history."
        }), 502


@app.post("/api/workflows/dispatch")
def workflow_dispatch():
    err = require_auth()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    workflow = str(body.get("workflow", "")).strip()

    allowed = {
        "stock_checker.yml",
        "watchlist_manager.yml",
        "earnings_report.yml",
        "economic_alert.yml",
        "heartbeat.yml",
        "portfolio_summary.yml",
    }

    if workflow not in allowed:
        return jsonify({
            "error": "Workflow is not on the dashboard allowlist."
        }), 400

    cfg = config()

    try:
        response = requests.post(
            api_repo_url(
                f"actions/workflows/{quote(workflow, safe='')}/dispatches"
            ),
            headers=gh_headers(),
            json={"ref": cfg["branch"]},
            timeout=20,
        )

        if response.status_code != 204:
            app.logger.error(
                "Workflow dispatch failed: %s %s",
                response.status_code,
                response.text[:300],
            )
            return jsonify({
                "error": (
                    f"GitHub could not dispatch workflow "
                    f"({response.status_code}). Check Actions permissions "
                    "and the workflow filename."
                )
            }), response.status_code

        return jsonify({
            "ok": True,
            "message": (
                f"Dispatch requested for {workflow}. "
                "Refresh workflow history in a few seconds."
            ),
        })

    except requests.RequestException:
        app.logger.exception("GitHub request failed while dispatching workflow")
        return jsonify({
            "error": "Could not contact GitHub to dispatch the workflow."
        }), 502


@app.post("/api/discord/test")
def discord_test():
    err = require_auth()
    if err:
        return err

    hook = os.getenv("DISCORD_STOCK_WEBHOOK", "").strip()
    if not hook:
        return jsonify({
            "error": "DISCORD_STOCK_WEBHOOK is not configured on the dashboard server."
        }), 503

    try:
        response = requests.post(
            hook,
            json={
                "content": (
                    "✅ Stock Alerts dashboard test: "
                    "Discord webhook delivery succeeded."
                )
            },
            timeout=15,
        )

        if response.status_code not in (200, 204):
            app.logger.error(
                "Discord webhook rejected test: %s %s",
                response.status_code,
                response.text[:200],
            )
            return jsonify({
                "error": f"Discord rejected the test ({response.status_code})."
            }), 502

        return jsonify({
            "ok": True,
            "message": "Discord accepted the test message.",
        })

    except requests.RequestException:
        app.logger.exception("Discord webhook request failed")
        return jsonify({
            "error": "Could not contact Discord."
        }), 502


# ---------------------------------------------------------
# PUBLIC READ-ONLY DASHBOARD
# ---------------------------------------------------------

@app.get("/public")
def public_dashboard():
    """Serve the public, read-only dashboard."""
    return send_from_directory(app.static_folder, "public.html")


@app.get("/api/public/portfolio")
def public_portfolio_get():
    """Return a sanitized portfolio for public viewing."""
    try:
        portfolio, _ = get_file(
            "portfolio/marks_portfolio.json",
            data=True,
        )

        if not isinstance(portfolio, dict):
            return jsonify({"error": "Invalid portfolio data."}), 502

        positions = []
        total_cost = 0.0

        for ticker, item in portfolio.items():
            if ticker == "closed_positions" or not isinstance(item, dict):
                continue

            try:
                shares = float(item.get("shares", 0) or 0)
                avg_price = float(item.get("avg_price", 0) or 0)
            except (TypeError, ValueError):
                continue

            if shares <= 0 or avg_price < 0:
                continue

            cost_basis = shares * avg_price
            total_cost += cost_basis

            # Keep these values server-side; never return them.
            positions.append({
                "ticker": str(ticker).upper(),
                "_cost_basis": cost_basis,
                "avg_price": avg_price,
            })

        if total_cost > 0:
            for position in positions:
                position["allocation_pct"] = round(
                    position["_cost_basis"] / total_cost * 100,
                    2,
                )

        # Remove the private calculation field before responding.
        public_positions = [
            {
                "ticker": p["ticker"],
                "avg_price": p["avg_price"],
                "allocation_pct": p.get("allocation_pct", 0),
            }
            for p in positions
        ]

        public_positions.sort(
            key=lambda p: p["allocation_pct"],
            reverse=True,
        )

        return jsonify({
            "positions": public_positions,
            "position_count": len(public_positions),
            "allocation_basis": "recorded cost basis",
            "note": (
                "Allocation percentages are based on recorded cost basis, "
                "not live market values. Share counts, total invested, "
                "and dollar-denominated position values are not published."
            ),
        })

    except (requests.RequestException, ValueError, KeyError,
            TypeError, RuntimeError):
        app.logger.exception("Could not load public portfolio")
        return jsonify({
            "error": "Could not load public portfolio data."
        }), 502


@app.get("/api/public/watchlist")
def public_watchlist_get():
    """Publish watchlist tickers and targets without write access."""
    try:
        watchlist, _ = get_file("alerts/watchlist.json", data=True)

        if not isinstance(watchlist, dict):
            return jsonify({"error": "Invalid watchlist data."}), 502

        # Explicit allowlist: only ticker names and configured targets.
        public_watchlist = {}

        for ticker, item in watchlist.items():
            if not isinstance(item, dict):
                continue

            price_targets = item.get("price_targets", [])
            valuation_targets = item.get("valuation_targets", {})

            if not isinstance(price_targets, list):
                price_targets = []

            if not isinstance(valuation_targets, dict):
                valuation_targets = {}

            clean_valuation = {}
            for metric in ("FxPE", "PE", "P/S"):
                directions = valuation_targets.get(metric, {})
                if not isinstance(directions, dict):
                    continue

                clean_directions = {}
                for direction in ("trim", "buy"):
                    values = directions.get(direction, [])
                    if isinstance(values, list):
                        clean_directions[direction] = [
                            v for v in values
                            if isinstance(v, (int, float))
                            and not isinstance(v, bool)
                        ]

                if clean_directions:
                    clean_valuation[metric] = clean_directions

            public_watchlist[str(ticker).upper()] = {
                "price_targets": [
                    v for v in price_targets
                    if isinstance(v, (int, float))
                    and not isinstance(v, bool)
                ],
                "valuation_targets": clean_valuation,
            }

        return jsonify(public_watchlist)

    except (requests.RequestException, ValueError, KeyError,
            TypeError, RuntimeError):
        app.logger.exception("Could not load public watchlist")
        return jsonify({
            "error": "Could not load public watchlist data."
        }), 502


@app.get("/api/public/analytics")
def public_analytics_get():
    """Read-only public analytics. Response is an explicit safe-field allowlist."""
    period = request.args.get("period", "1M").upper()
    if period not in ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "ALL"):
        return jsonify({"error": "Unsupported period."}), 400
    try:
        from public_analytics import get_public_analytics
        portfolio, _ = get_file("portfolio/marks_portfolio.json", data=True)
        if not isinstance(portfolio, dict):
            return jsonify({"error": "Invalid portfolio data."}), 502
        result = get_public_analytics(portfolio, period)
        response = jsonify(result)
        response.headers["Cache-Control"] = "public, max-age=60"
        return response
    except (requests.RequestException, RuntimeError, ValueError, TypeError, KeyError, ImportError):
        app.logger.exception("Could not calculate public analytics")
        return jsonify({"error": "Could not load market analytics."}), 502


@app.get("/api/public/analytics/snapshot")
def public_analytics_snapshot_get():
    """Fixed current allocations and holdings, public safe fields only."""
    try:
        from public_analytics import get_public_snapshot
        portfolio, _ = get_file("portfolio/marks_portfolio.json", data=True)
        if not isinstance(portfolio, dict):
            return jsonify({"error": "Invalid portfolio data."}), 502
        response = jsonify(get_public_snapshot(portfolio))
        response.headers["Cache-Control"] = "public, max-age=60"
        return response
    except (requests.RequestException, RuntimeError, ValueError, TypeError,
            KeyError, ImportError):
        app.logger.exception("Could not load public analytics snapshot")
        return jsonify({"error": "Could not load portfolio snapshot."}), 502


@app.get("/api/public/workflows")
def public_workflows_get():
    """Publish workflow status and run timestamps only."""
    try:
        cfg = config()
        response = requests.get(
            api_repo_url("actions/runs"),
            headers=gh_headers(),
            params={
                "branch": cfg["branch"],
                "per_page": 10,
            },
            timeout=20,
        )
        response.raise_for_status()

        runs = []
        for item in response.json().get("workflow_runs", []):
            runs.append({
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "created_at": item.get("created_at"),
                "html_url": item.get("html_url"),
            })

        return jsonify(runs)

    except (requests.RequestException, ValueError, KeyError, TypeError):
        app.logger.exception("Could not load public workflow history")
        return jsonify({
            "error": "Could not load workflow history."
        }), 502



if __name__ == "__main__":
    # Local development only. Use Gunicorn for deployment.
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8000")),
        debug=False,
    )
