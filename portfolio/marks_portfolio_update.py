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
    """Fetch latest price from Yahoo Finance. Returns 0.0 if unavailable."""
    try:
        stock = yf.Ticker(ticker)
        price = getattr(stock.fast_info, "last_price", None) or getattr(stock.fast_info, "lastPrice", None)
        if price is not None and math.isfinite(price):
            return float(price)
    except Exception as e:
        print(f"Warning: Could not fetch price for {ticker}: {e}")
    return 0.0


# -----------------------------------------------------------------------------
# Portfolio I/O (atomic)
# -----------------------------------------------------------------------------

def load_portfolio():
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    data.setdefault("closed_positions", [])

    # Migrate old format [shares, price] to dict
    for ticker, value in list(data.items()):
        if ticker == "closed_positions":
            continue
        if isinstance(value, list) and len(value) == 2:
            shares, price = value
            data[ticker] = {
                "shares": shares,
                "avg_price": price,
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
    tmp = PORTFOLIO_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, PORTFOLIO_FILE)
        print("Portfolio saved.")
    except Exception as e:
        print(f"Error saving: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# -----------------------------------------------------------------------------
# Compute cost basis for closed positions
# -----------------------------------------------------------------------------

def compute_cost_basis(transactions):
    total = 0.0
    for t in transactions:
        if t.get("action") == "BUY":
            total += t["shares"] * t["price"]
    return total


# -----------------------------------------------------------------------------
# Fetch current values
# -----------------------------------------------------------------------------

def fetch_portfolio_values(portfolio):
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
            print(f"Warning: Using avg_price as fallback for {ticker}")
            current_price = avg_price

        val = shares * current_price
        cost = shares * avg_price
        unrealized_pct = ((val - cost) / cost * 100) if cost > 0 else 0

        total_val += val
        total_cost_open += cost

        results.append({
            "ticker": ticker,
            "value": val,
            "unrealized_pct": unrealized_pct,
        })

    # Compute allocation percentages
    for r in results:
        r["allocation_pct"] = (r["value"] / total_val * 100) if total_val > 0 else 0

    return results, total_val, total_cost_open


# -----------------------------------------------------------------------------
# Table builder (no extra columns)
# -----------------------------------------------------------------------------

def build_summary_table(results):
    lines = [
        "```",
        f"{'Ticker':<8} {'Alloc%':>8} {'Unreal%':>9}",
        "-------- -------- ---------"
    ]
    for r in results:
        lines.append(f"{r['ticker']:<8} {r['allocation_pct']:>7.1f}% {r['unrealized_pct']:>8.1f}%")
    lines.append("```")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Chart
# -----------------------------------------------------------------------------

def generate_pie_chart(results):
    results.sort(key=lambda x: x['value'], reverse=True)
    labels = [f"{item['ticker']} ({item['allocation_pct']:.1f}%)" for item in results]
    values = [item['value'] for item in results]

    plt.figure(figsize=(10, 8))
    colors = plt.cm.tab20c.colors
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140,
            colors=colors, pctdistance=0.85, wedgeprops={'edgecolor': 'white', 'linewidth': 1})
    centre_circle = plt.Circle((0, 0), 0.70, fc='white')
    plt.gca().add_artist(centre_circle)
    plt.title('Portfolio Allocation', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=200)
    plt.close()
    return CHART_FILE


# -----------------------------------------------------------------------------
# Discord
# -----------------------------------------------------------------------------

def post_to_discord(title, description, color, chart_path=None):
    if not WEBHOOK_URL:
        print("Error: DISCORD_PORTFOLIO_WEBHOOK not set.")
        return

    payload = {
        "username": "Marks Portfolio",
        "embeds": [{"title": title, "description": description, "color": color}]
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
        print("Discord sent.")
    except requests.Timeout:
        print("Discord timeout.")
    except Exception as e:
        print(f"Discord error: {e}")


# -----------------------------------------------------------------------------
# STATUS
# -----------------------------------------------------------------------------

def post_status_summary():
    portfolio = load_portfolio()
    results, total_val, total_cost_open = fetch_portfolio_values(portfolio)
    chart_path = generate_pie_chart(results)
    table = build_summary_table(results)

    # Total return including closed positions
    closed_positions = portfolio.get("closed_positions", [])
    total_realized_closed = sum(pos.get("total_realized_pl", 0) for pos in closed_positions)
    total_cost_closed = sum(pos.get("total_cost_basis", 0) for pos in closed_positions)
    total_cost_all = total_cost_open + total_cost_closed
    total_unrealized = total_val - total_cost_open
    total_return_pct = ((total_unrealized + total_realized_closed) / total_cost_all * 100) if total_cost_all > 0 else 0

    description = f"**Lifetime Return:** {total_return_pct:+.1f}%\n\n{table}"
    post_to_discord("📊 MARKS PORTFOLIO", description, color=3447003, chart_path=chart_path)


# -----------------------------------------------------------------------------
# BUY / SELL
# -----------------------------------------------------------------------------

def execute_trade(action, ticker, shares_change, price):
    if shares_change <= 0:
        raise ValueError("Shares must be positive.")
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
            "transactions": old_info.get("transactions", []) + [transaction],
            "realized_pl": old_info.get("realized_pl", 0.0)
        }

    elif action == "SELL":
        if ticker not in portfolio:
            raise ValueError(f"Cannot sell {ticker}: position not found.")
        old_info = portfolio[ticker]
        old_shares = old_info["shares"]
        old_avg = old_info["avg_price"]

        if shares_change > old_shares:
            raise ValueError(f"Cannot sell {shares_change} shares; only {old_shares} held.")

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
            # Archive closed position
            total_cost_basis = compute_cost_basis(old_info.get("transactions", []))
            portfolio["closed_positions"].append({
                "ticker": ticker,
                "closure_date": datetime.now().date().isoformat(),
                "total_cost_basis": total_cost_basis,
                "total_realized_pl": new_realized_pl,
                "transactions": old_info.get("transactions", []) + [transaction],
            })
            del portfolio[ticker]
        else:
            portfolio[ticker]["shares"] = new_shares
            portfolio[ticker]["avg_price"] = old_avg
            portfolio[ticker]["transactions"] = old_info.get("transactions", []) + [transaction]
            portfolio[ticker]["realized_pl"] = new_realized_pl

    save_portfolio(portfolio)

    # Post updated status after trade
    results, total_val, _ = fetch_portfolio_values(portfolio)
    chart_path = generate_pie_chart(results)
    table = build_summary_table(results)

    # Find new weight of ticker if still open
    ticker_info = next((r for r in results if r["ticker"] == ticker), None)
    new_weight = ticker_info["allocation_pct"] if ticker_info else 0.0

    desc = f"**{action}** {shares_change} shares of **{ticker}**\nNew weight: **{new_weight:.1f}%**\n\n{table}"
    color = 3066993 if action == "BUY" else 15158332
    post_to_discord(f"📈 PORTFOLIO UPDATE: {action} {ticker}", desc, color, chart_path=chart_path)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1].upper() == "STATUS":
            post_status_summary()
        elif len(sys.argv) >= 5:
            action = sys.argv[1].upper()
            ticker = sys.argv[2].upper()
            shares = int(sys.argv[3])
            price = float(sys.argv[4])
            execute_trade(action, ticker, shares, price)
        else:
            print("Usage:")
            print("  STATUS: python marks_portfolio_update.py STATUS")
            print("  BUY:    python marks_portfolio_update.py BUY TICKER SHARES PRICE")
            print("  SELL:   python marks_portfolio_update.py SELL TICKER SHARES PRICE")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
