import os
import json
import time
import warnings
import requests
import yfinance as yf
import math

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

# Updated to match DISCORD_STOCK_WEBHOOK or fall back to DISCORD_WEBHOOK_URL
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STOCK_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")

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
    
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if response.status_code not in [200, 204]:
        print(f"Failed to send alert: {response.status_code}, {response.text}")
    else:
        print(f"Discord notification sent successfully for {symbol}.")

def check_prices():
    watchlist = load_watchlist()
    if not watchlist:
        print("No tickers found in watchlist.")
        return

    tickers_str = " ".join(watchlist.keys())
    try:
        data = yf.Tickers(tickers_str)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize market data client: {e}") from e
    
    modified = False
    updated_watchlist = {}

    for symbol, targets in watchlist.items():
        try:
            ticker_info = data.tickers[symbol].fast_info
            
            # Safely extract last_price and day_low across yfinance versions
            current_price = getattr(ticker_info, 'last_price', None) or getattr(ticker_info, 'lastPrice', None)
            day_low = getattr(ticker_info, 'day_low', None) or getattr(ticker_info, 'dayLow', None)
            
            # Fall back to current_price if day_low is unavailable
            check_price = day_low if day_low is not None else current_price

            if check_price is None or not isinstance(check_price, (int, float)) or not math.isfinite(float(check_price)):
                print(f"Warning: Could not fetch valid price data for {symbol}; keeping targets unchanged.")
                updated_watchlist[symbol] = targets
                continue

            remaining_targets = []
            for target in targets:
                # Check if price touched or dipped below target
                if check_price <= target:
                    print(f"ALERT TRIGGERED: {symbol} (Day Low ${check_price:.2f} <= Target ${target:.2f})")
                    send_discord_alert(symbol, current_price or check_price, check_price, target)
                    modified = True
                else:
                    print(f"OK: {symbol} (Day Low ${check_price:.2f}) > Target (${target:.2f})")
                    remaining_targets.append(target)

            if remaining_targets:
                updated_watchlist[symbol] = remaining_targets

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            updated_watchlist[symbol] = targets

    if modified:
        save_watchlist(updated_watchlist)

if __name__ == "__main__":
    print("Checking stock prices...")
    check_prices()
