import os
import sys
import json
import math
from datetime import datetime
import requests
import matplotlib.pyplot as plt
import yfinance as yf

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_PORTFOLIO_WEBHOOK")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "marks_portfolio.json")
CHART_FILE = os.path.join(BASE_DIR, "portfolio_chart.png")


def get_current_price(ticker: str) -> float:
    """
    Fetch the latest price from Yahoo Finance.
    Returns 0.0 if unavailable (caller must handle fallback).
    """
    try:
        stock = yf.Ticker(ticker)
        price = getattr(stock.fast_info, "last_price", None) or getattr(stock.fast_info, "lastPrice", None)
        if price is not None and math.isfinite(price):
            return float(price)
    except Exception as e:
        print(f"Warning: Could not fetch price for {ticker}: {e}")
    return 0.0


# -----------------------------------------------------------------------------
# Portfolio file I/O with atomic writes
# -----------------------------------------------------------------------------

def load_portfolio():
    """Load portfolio and convert old [shares, price] format to full dict."""
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    data.setdefault("closed_positions", [])

    # Migrate old format
    for ticker, value in list(data.items()):
        if ticker == "closed_positions":
            continue
        if isinstance(value, list) and len(value) == 2:
            shares, price = value
            data[ticker] = {
                "shares": shares,
                "avg_price": price,
                "currency": "USD",
                "account": "Merrill",
                "target_pct": 0.0,
                "conviction": "N/A",
                "desired_buy_range": [0, 0],
                "transactions": [
                    {"date": datetime.now().date().isoformat(),
                     "action": "BUY",
                     "shares": shares,
                     "price": price,
                     "fee": 0.0}
                ],
                "realized_pl": 0.0
            }
    return data


def save_portfolio(portfolio):
    """Atomically write portfolio to disk using a temporary file."""
    tmp_file = PORTFOLIO_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_file, PORTFOLIO_FILE)
        print("Portfolio saved atomically.")
    except Exception as e:
        print(f"Error saving portfolio: {e}")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        raise


# -----------------------------------------------------------------------------
# Cost basis helper
# -----------------------------------------------------------------------------

def compute_cost_basis(transactions):
    """Sum all BUY transaction amounts (shares * price) to get total cost basis."""
    total = 0.0
    for t in transactions:
        if t.get("action") == "BUY":
            total += t["shares"] * t["price"]
    return total


# -----------------------------------------------------------------------------
# Fetch live values and compute metrics
# -----------------------------------------------------------------------------

def fetch_portfolio_values(portfolio):
    """
    For each open ticker, fetch current price and compute:
        - current value, allocation %, unrealised P&L %
        - also collect cost basis for open positions
    Returns (results, total_value, total_cost_open)
    """
    results = []
    total_val = 0.0
    total_cost_open = 0.0

    for ticker, info in portfolio.items():
        if ticker == "closed_positions":
            continue

        shares = info["shares"]
        avg_price = info["avg_price"]
        current_price = get_current_price(ticker)

        if current_price == 0.0:
            print(f"Warning: Using avg_price as fallback for {ticker} (no live price).")
            current_price = avg_price

        val = shares * current_price
        cost = shares * avg_price
        unrealized_pct = ((val - cost) / cost * 100) if cost > 0 else 0

        total_val += val
        total_cost_open += cost

        results.append({
            "ticker": ticker,
            "value": val,
            "account": info.get("account", ""),
            "unrealized_pct": unrealized_pct,
            "target_pct": info.get("target_pct", 0.0),
            "conviction": info.get("conviction", "N/A"),
            "buy_low": info.get("desired_buy_range", [0, 0])[0],
            "buy_high": info.get("desired_buy_range", [0, 0])[1],
            "shares": shares,
            "avg_price": avg_price,
            "current_price": current_price
        })

    # Second pass: compute allocation percentages
    for r in results:
        r["allocation_pct"] = (r["value"] / total_val * 100) if total_val > 0 else 0

    return results, total_val, total_cost_open


def build_summary_table(results):
    """Build a Markdown table (inside code block) with only percentages."""
    lines = [
        "```",
        f"{'Ticker':<8} {'Account':<10} {'Alloc%':>7} {'Unreal%':>8} {'Target%':>8} {'Conviction':<12} {'Buy Range'}",
        "-------- ---------- ------- -------- -------- ------------ ----------"
    ]
    for r in results:
        lines.append(
            f"{r['ticker']:<8} {r['account']:<10} {r['allocation_pct']:>6.1f}% {r['unrealized_pct']:>7.1f}% {r['target_pct']:>7.1f}% {r['conviction']:<12} {r['buy_low']:.0f}-{r['buy_high']:.0f}"
        )
    lines.append("```")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Chart generation
# -----------------------------------------------------------------------------

def generate_pie_chart(results):
    """Generate pie chart showing allocation percentages."""
    results.sort(key=lambda x: x['value'], reverse=True)
    labels = [f"{item['ticker']} ({item['allocation_pct']:.1f}%)" for item in results]
    values = [item['value'] for item in results]

    plt.figure(figsize=(10, 8))
    colors = plt.cm.tab20c.colors
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140,
            colors=colors, pctdistance=0.85, wedgeprops={'edgecolor': 'white', 'linewidth': 1})
    centre_circle = plt.Circle((0, 0), 0.70, fc='white')
    plt.gca().add_artist(centre_circle)
    plt.title('Portfolio Allocation (by position weight)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=200)
    plt.close()
    return CHART_FILE


# -----------------------------------------------------------------------------
# Discord posting with timeout
# -----------------------------------------------------------------------------

def post_to_discord(title, description, color, chart_path=None):
    """Send an embed with optional pie chart attachment (with timeout)."""
    if not WEBHOOK_URL:
        print("Error: DISCORD_PORTFOLIO_WEBHOOK not set.")
        return

    payload = {
        "username": "Marks Portfolio",
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
        }]
    }

    try:
        if chart_path and os.path.exists(chart_path):
            payload["embeds"][0]["image"] = {"url": "attachment://portfolio_chart.png"}
            with open(chart_path, "rb") as f:
                files = {"file": (chart_path, f, "image/png")}
                requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)},
                              files=files, timeout=15)
        else:
            requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print("Discord message sent.")
    except requests.Timeout:
        print("Discord request timed out.")
    except Exception as e:
        print(f"Failed to send Discord message: {e}")


# -----------------------------------------------------------------------------
# Status summary (STATUS)
# -----------------------------------------------------------------------------

def post_status_summary():
    portfolio = load_portfolio()
    results, total_val, total_cost_open = fetch_portfolio_values(portfolio)
    chart_path = generate_pie_chart(results)
    table = build_summary_table(results)

    # ---- Compute returns using proper denominator ----
    total_unrealized = total_val - total_cost_open

    # Closed positions
    closed_positions = portfolio.get("closed_positions", [])
    total_realized_closed = sum(pos.get("total_realized_pl", 0) for pos in closed_positions)
    total_cost_closed = sum(pos.get("total_cost_basis", 0) for pos in closed_positions)

    total_cost_all = total_cost_open + total_cost_closed
    total_return_all = ((total_unrealized + total_realized_closed) / total_cost_all * 100) if total_cost_all > 0 else 0

    description = (
        f"**Lifetime Return (on total invested):** {total_return_all:+.1f}%\n"
        f"*(Open positions: {total_unrealized:+.2f} unrealized / Closed positions: {total_realized_closed:+.2f} realized)*\n\n"
        f"{table}"
    )

    post_to_discord("📊 MARKS PORTFOLIO: CURRENT OVERVIEW",
                    description, color=3447003, chart_path=chart_path)


# -----------------------------------------------------------------------------
# Trade execution (BUY / SELL) with validation & closed position archiving
# -----------------------------------------------------------------------------

def execute_trade(action, ticker, shares_change, price):
    # --- Input validation ---
    if shares_change <= 0:
        raise ValueError("Number of shares must be positive.")
    if price <= 0:
        raise ValueError("Price must be positive.")
    if action not in ("BUY", "SELL"):
        raise ValueError("Action must be BUY or SELL.")

    portfolio = load_portfolio()
    portfolio.setdefault("closed_positions", [])

    if action == "BUY":
        old_info = portfolio.get(ticker, {})
        old_shares = old_info.get("shares", 0)
        old_avg = old_info.get("avg_price", 0.0)

        new_shares = old_shares + shares_change
        new_avg = ((old_shares * old_avg) + (shares_change * price)) / new_shares if new_shares > 0 else 0

        transaction = {
            "date": datetime.now().date().isoformat(),
            "action": "BUY",
            "shares": shares_change,
            "price": price,
            "fee": 0.0
        }

        portfolio[ticker] = {
            "shares": new_shares,
            "avg_price": round(new_avg, 2),
            "currency": old_info.get("currency", "USD"),
            "account": old_info.get("account", "Merrill"),
            "target_pct": old_info.get("target_pct", 0.0),
            "conviction": old_info.get("conviction", "N/A"),
            "desired_buy_range": old_info.get("desired_buy_range", [0, 0]),
            "transactions": old_info.get("transactions", []) + [transaction],
            "realized_pl": old_info.get("realized_pl", 0.0)
        }

    elif action == "SELL":
        if ticker not in portfolio:
            raise ValueError(f"Cannot sell {ticker}: position does not exist.")
        old_info = portfolio[ticker]
        old_shares = old_info["shares"]
        old_avg = old_info["avg_price"]

        if shares_change > old_shares:
            raise ValueError(f"Cannot sell {shares_change} shares of {ticker}: only {old_shares} held.")

        realized_gain = (price - old_avg) * shares_change
        new_shares = old_shares - shares_change

        transaction = {
            "date": datetime.now().date().isoformat(),
            "action": "SELL",
            "shares": shares_change,
            "price": price,
            "fee": 0.0
        }

        new_realized_pl = old_info.get("realized_pl", 0.0) + realized_gain

        if new_shares <= 0:
            # --- Archive closed position with its total cost basis ---
            total_cost_basis = compute_cost_basis(old_info.get("transactions", []))
            closed_entry = {
                "ticker": ticker,
                "closure_date": datetime.now().date().isoformat(),
                "total_cost_basis": total_cost_basis,
                "total_realized_pl": new_realized_pl,
                "transactions": old_info.get("transactions", []) + [transaction],
                "final_avg_price": old_avg,
                "final_shares": old_shares
            }
            portfolio["closed_positions"].append(closed_entry)
            del portfolio[ticker]
        else:
            portfolio[ticker]["shares"] = new_shares
            portfolio[ticker]["avg_price"] = old_avg
            portfolio[ticker]["transactions"] = old_info.get("transactions", []) + [transaction]
            portfolio[ticker]["realized_pl"] = new_realized_pl

    save_portfolio(portfolio)

    # After trade, post updated status
    results, total_val, _ = fetch_portfolio_values(portfolio)
    chart_path = generate_pie_chart(results)
    table = build_summary_table(results)

    ticker_info = next((r for r in results if r["ticker"] == ticker), None)
    new_weight = ticker_info["allocation_pct"] if ticker_info else 0.0

    desc = f"Mark **{'bought' if action == 'BUY' else 'sold'}** {shares_change} shares of **{ticker}**.\n"
    desc += f"New Position Weight: **{new_weight:.1f}%** of portfolio.\n\n"
    desc += table

    color = 3066993 if action == "BUY" else 15158332
    post_to_discord(f"📈 PORTFOLIO UPDATE: {action} {ticker}",
                    desc, color=color, chart_path=chart_path)


# -----------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1].upper() in ["STATUS", "SUMMARY"]:
            post_status_summary()
        elif len(sys.argv) >= 5:
            trade_action = sys.argv[1].upper()
            trade_ticker = sys.argv[2].upper()
            trade_shares = int(sys.argv[3])
            trade_price = float(sys.argv[4])
            execute_trade(trade_action, trade_ticker, trade_shares, trade_price)
        else:
            print("Usage:")
            print("  Status:  python portfolio/marks_portfolio_update.py STATUS")
            print("  Trade:   python portfolio/marks_portfolio_update.py BUY TICKER SHARES PRICE")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
        
