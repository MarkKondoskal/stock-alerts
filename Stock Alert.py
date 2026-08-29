import os
import json
import time
import warnings
import requests
import yfinance as yf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
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
                    {"name": "Target Price Hit", "value": f"${target_price:.2f}", "inline": True},
                ],
                "footer": {"text": "Target met and removed from watchlist"},
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
    
    modified = False
    updated_watchlist = {}

    for symbol, targets in watchlist.items():
        try:
            price = data.tickers[symbol].fast_info['lastPrice']
            if price is None:
                updated_watchlist[symbol] = targets
                continue

            remaining_targets = []
            for target in targets:
                if price <= target:
                    print(f"ALERT TRIGGERED: {symbol} (${price:.2f} <= ${target:.2f})")
                    send_discord_alert(symbol, price, target)
                    modified = True  # Target reached, drop it from remaining_targets
                else:
                    print(f"OK: {symbol} (${price:.2f}) > target (${target:.2f})")
                    remaining_targets.append(target)

            # Retain symbol only if remaining targets exist
            if remaining_targets:
                updated_watchlist[symbol] = remaining_targets

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            updated_watchlist[symbol] = targets

    # Save changes locally if any targets were hit
    if modified:
        save_watchlist(updated_watchlist)

if __name__ == "__main__":
    print("Checking prices...")
    check_prices()
