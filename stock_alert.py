import os
import json
import time
import warnings
import requests
import yfinance as yf

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

# Updated to match DISCORD_STOCK_WEBHOOK or fall back to DISCORD_WEBHOOK_URL
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STOCK_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL")
WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {WATCHLIST_FILE}: {e}")
        return {}

def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=2)
        print("Updated watchlist.json saved successfully.")
    except Exception as e:
        print(f"Error saving {WATCHLIST_FILE}: {e}")

def send_discord_alert(symbol, current_price, day_low, target_price):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing.")
        return

    payload = {
        "username": "Stock Alerter",
        "embeds": [
            {
                "title": f"🚨 PRICE TARGET HIT: {symbol}",
                "color": 5763719,  # Green embed color
                "fields": [
                    {"name": "Target Price", "value": f"${target_price:.2f}", "inline": True},
                    {"name": "Day's Low", "value": f"${day_low:.2f}", "inline": True},
                    {"name": "Current Price", "value": f"${current_price:.2f}", "inline": True},
                ],
                "footer": {"text": "Target met today and auto-removed from watchlist"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }
    
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if response.status_code not in [200, 204]:
        print(f"Failed to send alert: {response.status_code}, {response.text}")
    else:
        print(f"Discord notification sent successfully for {symbol}.")

def check_prices():
    watchlist = load_watchlist()
    if not watchlist:
        print("No tickers found in watchlist.")
        return

    modified = False
    updated_watchlist = {}

    for symbol, targets in watchlist.items():
        # Hardcode test prices for weekend verification
        current_price = 180.00
        day_low = 175.00
        check_price = day_low

        remaining_targets = []
        for target in targets:
            if check_price <= target:
                print(f"TEST ALERT TRIGGERED: {symbol} (Price ${check_price:.2f} <= Target ${target:.2f})")
                send_discord_alert(symbol, current_price, check_price, target)
                modified = True
            else:
                remaining_targets.append(target)

        if remaining_targets:
            updated_watchlist[symbol] = remaining_targets

    if modified:
        save_watchlist(updated_watchlist)

if __name__ == "__main__":
    print("Checking stock prices...")
    check_prices()
