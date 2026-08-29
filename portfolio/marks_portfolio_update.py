import os
import sys
import json
import math
import requests
import matplotlib.pyplot as plt
import yfinance as yf

WEBHOOK_URL = os.environ.get("DISCORD_PORTFOLIO_WEBHOOK")

# Dynamic directory path targeting marks_portfolio.json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "marks_portfolio.json")

def load_portfolio():
    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)

def fetch_portfolio_values(portfolio):
    results = []
    total_val = 0.0
    total_cost = 0.0

    for ticker, (shares, buy_price) in portfolio.items():
        try:
            stock = yf.Ticker(ticker)
            price = getattr(stock.fast_info, 'last_price', None) or getattr(stock.fast_info, 'lastPrice', None)
            if price is None or math.isnan(price):
                price = buy_price

            val = shares * price
            cost = shares * buy_price
            ret_pct = ((val - cost) / cost * 100) if cost > 0 else 0

            total_val += val
            total_cost += cost
            results.append({"ticker": ticker, "value": val, "return_pct": ret_pct})
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")

    return results, total_val, total_val - total_cost

def generate_pie_chart(results, total_profit):
    results.sort(key=lambda x: x['value'], reverse=True)
    labels = [f"{item['ticker']} ({item['return_pct']:+.1f}%)" for item in results]
    values = [item['value'] for item in results]

    plt.figure(figsize=(10, 8))
    colors = plt.cm.tab20c.colors
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140, colors=colors, pctdistance=0.85, wedgeprops={'edgecolor': 'white', 'linewidth': 1})
    centre_circle = plt.Circle((0,0), 0.70, fc='white')
    plt.gca().add_artist(centre_circle)
    plt.title(f'Portfolio Allocation\nNet P/L: ${total_profit:,.2f}', fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    chart_path = os.path.join(BASE_DIR, "portfolio_chart.png")
    plt.savefig(chart_path, dpi=200)
    plt.close()
    return chart_path

def post_status_summary():
    portfolio = load_portfolio()
    results, total_val, total_profit = fetch_portfolio_values(portfolio)
    chart_file = generate_pie_chart(results, total_profit)

    summary_text = f"**Current Portfolio Value:** ${total_val:,.2f}\n**Total Net Profit/Loss:** ${total_profit:,.2f}"

    if WEBHOOK_URL:
        payload = {
            "username": "Marks Portfolio",
            "embeds": [{
                "title": "📊 MARKS PORTFOLIO: CURRENT OVERVIEW",
                "description": summary_text,
                "color": 3447003,
                "image": {"url": "attachment://portfolio_chart.png"}
            }]
        }
        with open(chart_file, "rb") as f:
            requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": (chart_file, f, "image/png")})
        print("Portfolio status reminder posted to Discord successfully.")

def execute_trade(action, ticker, shares_change, price):
    portfolio = load_portfolio()
    old_shares, old_buy = portfolio.get(ticker, [0, 0.0])
    
    if action == "BUY":
        new_shares = old_shares + shares_change
        new_buy = ((old_shares * old_buy) + (shares_change * price)) / new_shares
        portfolio[ticker] = [new_shares, round(new_buy, 2)]
    elif action == "SELL":
        new_shares = max(0, old_shares - shares_change)
        if new_shares == 0:
            portfolio.pop(ticker, None)
        else:
            portfolio[ticker] = [new_shares, old_buy]

    save_portfolio(portfolio)

    results_after, total_val_after, net_profit = fetch_portfolio_values(portfolio)
    new_ticker_val = next((item['value'] for item in results_after if item['ticker'] == ticker), 0)
    new_weight = (new_ticker_val / total_val_after * 100) if total_val_after > 0 else 0

    chart_file = generate_pie_chart(results_after, net_profit)

    trade_text = f"Mark **{'bought' if action == 'BUY' else 'sold'}** {shares_change} shares of **{ticker}** at **${price:.2f}** per share.\nPosition Weight: **{new_weight:.1f}%** of portfolio."

    if WEBHOOK_URL:
        payload = {
            "username": "Marks Portfolio",
            "embeds": [{
                "title": f"📈 PORTFOLIO UPDATE: {action} {ticker}",
                "description": trade_text,
                "color": 3066993 if action == "BUY" else 15158332,
                "image": {"url": "attachment://portfolio_chart.png"}
            }]
        }
        with open(chart_file, "rb") as f:
            requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": (chart_file, f, "image/png")})
        print("Trade alert and pie chart posted to Discord successfully.")

if __name__ == "__main__":
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
        print("  Status check: python portfolio/marks_portfolio_update.py STATUS")
        print("  Trade execute: python portfolio/marks_portfolio_update.py BUY TICKER SHARES PRICE")
        sys.exit(1)
