import json
import math
import os
import time
import warnings

import requests
import yfinance as yf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STOCK_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
METRIC_KEYS = {
    "pe": ("trailingPE", "P/E"),
    "forward_pe": ("forwardPE", "Forward P/E"),
    "ps": ("priceToSalesTrailing12Months", "P/S"),
}


def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        print(f"Error loading {WATCHLIST_FILE}: {exc}")
        return {"stocks": {}, "research": {}}
    if isinstance(raw, dict) and "stocks" in raw:
        return {"stocks": raw.get("stocks", {}) or {}, "research": raw.get("research", {}) or {}}
    stocks = {}
    if isinstance(raw, dict):
        for symbol, targets in raw.items():
            if isinstance(targets, list):
                stocks[str(symbol).strip().upper()] = {"targets": sorted({float(t) for t in targets}), "valuation_targets": []}
    return {"stocks": stocks, "research": {}}


def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Updated watchlist.json saved successfully.")


def valid_number(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def valuation_snapshot(info):
    result = {}
    for key, (source_key, label) in METRIC_KEYS.items():
        value = info.get(source_key)
        result[key] = float(value) if valid_number(value) and float(value) > 0 else None
    return result


def send_alert(symbol, direction, target_text, current_price, reference_text, valuation=None):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing.")
        return False
    is_add = direction.upper() == "ADD"
    fields = [
        {"name": "Target", "value": target_text, "inline": True},
        {"name": "Current Price", "value": f"${current_price:,.2f}", "inline": True},
    ]
    if reference_text:
        fields.append({"name": "Observed", "value": reference_text, "inline": True})
    if valuation:
        vals = []
        for key, (_, label) in METRIC_KEYS.items():
            val = valuation.get(key)
            vals.append(f"{label}: {val:.1f}×" if val is not None else f"{label}: N/A")
        fields.append({"name": "Current Valuation", "value": "\n".join(vals), "inline": False})
    payload = {"username": "Stock Alerter", "embeds": [{
        "title": f"{'🟢' if is_add else '🔴'} {direction.upper()} TARGET HIT: {symbol}",
        "color": 5763719 if is_add else 15158332,
        "fields": fields,
        "footer": {"text": "Target met and removed after successful Discord delivery"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }]}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code not in (200, 204):
            print(f"Failed to send alert for {symbol}: {response.status_code}, {response.text}")
            return False
        return True
    except Exception as exc:
        print(f"Failed to send Discord alert for {symbol}: {exc}")
        return False


def check_prices():
    data = load_watchlist()
    stocks = data.get("stocks", {})
    if not stocks:
        print("No tickers found in watchlist.")
        return

    updated_stocks = {}
    modified = False
    for raw_symbol, raw_config in stocks.items():
        symbol = str(raw_symbol).strip().upper()
        config = raw_config if isinstance(raw_config, dict) else {"targets": raw_config}
        price_targets = sorted({float(t) for t in config.get("targets", []) if valid_number(t)})
        valuation_targets = [dict(t) for t in config.get("valuation_targets", []) if isinstance(t, dict)]
        try:
            ticker = yf.Ticker(symbol)
            fast = ticker.fast_info
            current_price = getattr(fast, "last_price", None) or getattr(fast, "lastPrice", None)
            day_low = getattr(fast, "day_low", None) or getattr(fast, "dayLow", None)
            day_high = getattr(fast, "day_high", None) or getattr(fast, "dayHigh", None)
            info = ticker.info or {}
            valuation = valuation_snapshot(info)
            if not valid_number(current_price):
                print(f"No valid price for {symbol}; retaining targets.")
                updated_stocks[symbol] = {"targets": price_targets, "valuation_targets": valuation_targets}
                continue
            current_price = float(current_price)
            day_low = float(day_low) if valid_number(day_low) else None
            day_high = float(day_high) if valid_number(day_high) else None

            remaining_prices = []
            for target in price_targets:
                direction = "ADD" if target < current_price else "TRIM"
                reference = day_low if direction == "ADD" else day_high
                hit = reference is not None and (reference <= target if direction == "ADD" else reference >= target)
                if hit:
                    sent = send_alert(symbol, direction, f"${target:,.2f}", current_price,
                                      f"${reference:,.2f}", valuation)
                    if not sent:
                        remaining_prices.append(target)
                else:
                    remaining_prices.append(target)

            remaining_valuations = []
            for target in valuation_targets:
                metric = str(target.get("metric", "")).lower().strip()
                direction = str(target.get("direction", "TRIM")).upper().strip()
                threshold = target.get("target")
                if metric not in METRIC_KEYS or direction not in {"ADD", "TRIM"} or not valid_number(threshold):
                    remaining_valuations.append(target)
                    continue
                current_multiple = valuation.get(metric)
                if current_multiple is None:
                    print(f"No {METRIC_KEYS[metric][1]} data for {symbol}; retaining valuation target.")
                    remaining_valuations.append(target)
                    continue
                hit = current_multiple >= float(threshold) if direction == "TRIM" else current_multiple <= float(threshold)
                if hit:
                    _, label = METRIC_KEYS[metric]
                    sent = send_alert(symbol, direction, f"{label} ≥ {float(threshold):.1f}×" if direction == "TRIM" else f"{label} ≤ {float(threshold):.1f}×",
                                      current_price, f"{label}: {current_multiple:.1f}×", valuation)
                    if not sent:
                        remaining_valuations.append(target)
                else:
                    remaining_valuations.append(target)

            updated_stocks[symbol] = {"targets": remaining_prices, "valuation_targets": remaining_valuations}
            if symbol != raw_symbol or remaining_prices != price_targets or remaining_valuations != valuation_targets:
                modified = True
        except Exception as exc:
            print(f"Error processing {symbol}: {exc}")
            updated_stocks[symbol] = {"targets": price_targets, "valuation_targets": valuation_targets}

    updated_stocks = {s: c for s, c in updated_stocks.items() if c.get("targets") or c.get("valuation_targets")}
    updated_data = {"stocks": updated_stocks, "research": data.get("research", {})}
    if modified or updated_stocks != stocks:
        save_watchlist(updated_data)


if __name__ == "__main__":
    print("Checking stock price and valuation targets...")
    check_prices()
