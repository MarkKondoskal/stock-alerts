import os
import json
import time
import warnings
import requests
import yfinance as yf
import math

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STOCK_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")


def normalize_entry(entry):
    # Backward compatibility with the old {"TICKER": [price targets]} format.
    if isinstance(entry, list):
        return {"price_targets": entry, "valuation_targets": {}}
    if isinstance(entry, dict):
        return {
            "price_targets": entry.get("price_targets", entry.get("price", [])),
            "valuation_targets": entry.get("valuation_targets", entry.get("valuation", {})),
        }
    return {"price_targets": [], "valuation_targets": {}}


def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            raw = json.load(f)
        return {str(symbol).strip().upper(): normalize_entry(entry) for symbol, entry in raw.items()}
    except Exception as e:
        print(f"Error loading {WATCHLIST_FILE}: {e}")
        return {}


def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=2)
        print("Updated watchlist.json saved successfully.")
    except Exception as e:
        print(f"Error saving watchlist: {e}")


def send_discord_alert(symbol, current_price, day_low, target_price):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing.")
        return
    payload = {"username": "Stock Alerter", "embeds": [{
        "title": f"🚨 PRICE TARGET HIT: {symbol}", "color": 5763719,
        "fields": [
            {"name": "Target Price", "value": f"${target_price:.2f}", "inline": True},
            {"name": "Day's Low", "value": f"${day_low:.2f}", "inline": True},
            {"name": "Current Price", "value": f"${current_price:.2f}", "inline": True},
        ],
        "footer": {"text": "Target met today and auto-removed from watchlist"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }]}
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

    price_symbols = [symbol for symbol, entry in watchlist.items() if entry["price_targets"]]
    if not price_symbols:
        print("No price targets to check. Valuation monitoring will be added in the next stage.")
        return

    try:
        data = yf.Tickers(" ".join(price_symbols))
    except Exception as e:
        raise RuntimeError(f"Failed to initialize market data client: {e}") from e

    modified = False
    updated_watchlist = {}
    for symbol, entry in watchlist.items():
        targets = entry["price_targets"]
        valuations = entry["valuation_targets"]
        if not targets:
            updated_watchlist[symbol] = entry
            continue
        try:
            ticker_info = data.tickers[symbol].fast_info
            current_price = getattr(ticker_info, "last_price", None) or getattr(ticker_info, "lastPrice", None)
            day_low = getattr(ticker_info, "day_low", None) or getattr(ticker_info, "dayLow", None)
            check_price = day_low if day_low is not None else current_price
            if check_price is None or not isinstance(check_price, (int, float)) or not math.isfinite(float(check_price)):
                print(f"Warning: Could not fetch valid price data for {symbol}; keeping targets unchanged.")
                updated_watchlist[symbol] = entry
                continue
            remaining_targets = []
            for target in targets:
                if check_price <= target:
                    print(f"ALERT TRIGGERED: {symbol} (Day Low ${check_price:.2f} <= Target ${target:.2f})")
                    send_discord_alert(symbol, float(current_price or check_price), float(check_price), float(target))
                    modified = True
                else:
                    remaining_targets.append(target)
            if remaining_targets or valuations:
                updated_watchlist[symbol] = {"price_targets": remaining_targets, "valuation_targets": valuations}
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            updated_watchlist[symbol] = entry

    if modified:
        save_watchlist(updated_watchlist)


if __name__ == "__main__":
    print("Checking stock prices...")
    check_prices()
