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


def _post_discord(payload):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing.")
        return False
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code not in (200, 204):
            print(f"Failed to send alert: {response.status_code}, {response.text}")
            return False
        return True
    except requests.RequestException as exc:
        print(f"Discord request failed: {exc}")
        return False


def send_discord_alert(symbol, current_price, day_low, target_price):
    payload = {"username": "Stock Alerter", "embeds": [{
        "title": f"🚨 PRICE TARGET HIT: {symbol}", "color": 5763719,
        "fields": [
            {"name": "Target Price", "value": f"${target_price:.2f}", "inline": True},
            {"name": "Day's Low", "value": f"${day_low:.2f}", "inline": True},
            {"name": "Current Price", "value": f"${current_price:.2f}", "inline": True},
        ],
        "footer": {"text": "Target met; removed only after successful notification"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }]}
    ok = _post_discord(payload)
    if ok:
        print(f"Discord price notification sent for {symbol}.")
    return ok


def send_valuation_alert(symbol, metric, current_value, target_value):
    labels = {"PE": "Trailing P/E", "FxPE": "Forward P/E", "P/S": "Price-to-Sales"}
    payload = {"username": "Stock Alerter", "embeds": [{
        "title": f"📊 VALUATION TARGET HIT: {symbol}", "color": 3447003,
        "fields": [
            {"name": "Metric", "value": labels[metric], "inline": True},
            {"name": "Target", "value": f"{target_value:.1f}x", "inline": True},
            {"name": "Latest value", "value": f"{current_value:.1f}x", "inline": True},
        ],
        "footer": {"text": "Valuation target met; removed only after successful notification"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }]}
    ok = _post_discord(payload)
    if ok:
        print(f"Discord valuation notification sent for {symbol} ({metric}).")
    return ok


def _positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def check_prices():
    watchlist = load_watchlist()
    if not watchlist:
        print("No tickers found in watchlist.")
        return

    modified = False
    updated_watchlist = {}
    for symbol, entry in watchlist.items():
        remaining_price_targets = []
        remaining_valuation_targets = {}
        price_targets = entry["price_targets"]
        valuation_targets = entry["valuation_targets"] if isinstance(entry["valuation_targets"], dict) else {}

        # Fetch one ticker object per symbol. Price-only tickers can use fast_info;
        # get_info is only needed for valuation targets.
        stock = yf.Ticker(symbol)
        current_price = day_low = None
        if price_targets:
            try:
                fast_info = stock.fast_info
                current_price = _positive_number(getattr(fast_info, "last_price", None)) or _positive_number(
                    getattr(fast_info, "lastPrice", None))
                day_low = _positive_number(getattr(fast_info, "day_low", None)) or _positive_number(
                    getattr(fast_info, "dayLow", None))
            except Exception as exc:
                print(f"Could not fetch price data for {symbol}: {exc}")

            check_price = day_low or current_price
            if check_price is None:
                print(f"No valid price data for {symbol}; retaining price targets.")
                remaining_price_targets = list(price_targets)
            else:
                for target in price_targets:
                    if check_price <= target:
                        if send_discord_alert(symbol, float(current_price or check_price), float(check_price), float(target)):
                            modified = True
                        else:
                            remaining_price_targets.append(target)
                    else:
                        remaining_price_targets.append(target)

        if valuation_targets:
            try:
                info = stock.get_info() or {}
            except Exception as exc:
                print(f"Could not fetch valuation data for {symbol}; retaining valuation targets: {exc}")
                info = None

            key_map = {"PE": "trailingPE", "FxPE": "forwardPE", "P/S": "priceToSalesTrailing12Months"}
            if info is None:
                remaining_valuation_targets = {k: list(v) for k, v in valuation_targets.items()}
            else:
                for metric, targets in valuation_targets.items():
                    metric_key = key_map.get(metric)
                    value = _positive_number(info.get(metric_key)) if metric_key else None
                    keep = []
                    for target in targets:
                        if value is None:
                            keep.append(target)
                        elif value >= float(target):
                            if send_valuation_alert(symbol, metric, value, float(target)):
                                modified = True
                            else:
                                keep.append(target)
                        else:
                            keep.append(target)
                    if keep:
                        remaining_valuation_targets[metric] = keep

        if remaining_price_targets or remaining_valuation_targets:
            updated_watchlist[symbol] = {
                "price_targets": remaining_price_targets,
                "valuation_targets": remaining_valuation_targets,
            }

    if modified:
        save_watchlist(updated_watchlist)
    else:
        print("No targets were successfully triggered; watchlist unchanged.")


if __name__ == "__main__":
    print("Checking stock prices...")
    check_prices()
