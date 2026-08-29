import os
import json
import time
import warnings
import requests
import yfinance as yf

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def load_watchlist(filepath="watchlist.json"):
    """Load stock targets dynamically from a JSON file."""
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return {}

def send_discord_alert(symbol, current_price, target_price):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")
        return

    payload = {
        "username": "Stock Monitor",
        "embeds": [
            {
                "title": f"🚨 PRICE TARGET ALERT: {symbol}",
                "color": 5763719,
                "fields": [
                    {"name": "Current Price", "value": f"${current_price:.2f}", "inline": True},
                    {"name": "Target Price", "value": f"${target_price:.2f}", "inline": True},
                ],
                "footer": {"text": "Stock Price Tracker"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }
    
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if response.status_code not in [200, 204]:
        print(f"Failed to send alert: {response.status_code}, {response.text}")

def check_prices():
    watchlist = load_watchlist()
    if not watchlist:
        print("No tickers found in watchlist.")
        return

    tickers_str = " ".join(watchlist.keys())
    data = yf.Tickers(tickers_str)
    
    for symbol, targets in watchlist.items():
        try:
            price = data.tickers[symbol].fast_info['lastPrice']
            if price is None:
                continue
                
            for target in targets:
                if price <= target:
                    print(f"ALERT: {symbol} price ${price:.2f} <= target ${target:.2f}")
                    send_discord_alert(symbol, price, target)
                else:
                    print(f"OK: {symbol} (${price:.2f}) > target (${target:.2f})")
                    
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

if __name__ == "__main__":
    print("Checking prices...")
    check_prices()
