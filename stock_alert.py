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
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")
        return

    payload = {
        "username": "Stock Monitor",
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
            ticker_info = data.tickers[symbol].fast_info
            
            # Fetch both current price and the minimum price reached today
            current_price = ticker_info.get('lastPrice')
            day_low = ticker_info.get('dayLow')
            
            # Fall back to current_price if day_low is unavailable
            check_price = day_low if day_low is not None else current_price

            if check_price is None:
                updated_watchlist[symbol] = targets
                continue

            remaining_targets = []
            for target in targets:
                # Check if the stock touched or dipped below the target at any point today
                if check_price <= target:
                    print(f"ALERT TRIGGERED: {symbol} (Day Low ${check_price:.2f} <= Target ${target:.2f})")
                    send_discord_alert(symbol, current_price, check_price, target)
                    modified = True  # Target breached; do not append to remaining_targets
                else:
                    print(f"OK: {symbol} (Day Low ${check_price:.2f}) > Target (${target:.2f})")
                    remaining_targets.append(target)

            # Keep symbol in JSON only if active targets remain
            if remaining_targets:
                updated_watchlist[symbol] = remaining_targets

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            updated_watchlist[symbol] = targets

    # Save updated watchlist locally if any target was hit
    if modified:
        save_watchlist(updated_watchlist)

if __name__ == "__main__":
    print("Checking prices...")
    check_prices()
