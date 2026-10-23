import json
import math
import os
import time
import warnings
from pathlib import Path

import requests
import yfinance as yf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STOCK_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL")
BASE_DIR = Path(__file__).resolve().parent
WATCHLIST_FILE = BASE_DIR / "watchlist.json"
VALUATION_INFO_KEYS = {
    "FxPE": "forwardPE",
    "PE": "trailingPE",
    "P/S": "priceToSalesTrailing12Months",
}


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def normalize_entry(entry):
    """Support legacy price-only entries and the current structured format."""
    if isinstance(entry, list):
        return {"price_targets": entry, "valuation_targets": {}}
    if isinstance(entry, dict):
        raw_valuations = entry.get("valuation_targets", entry.get("valuation", {}))
        return {
            "price_targets": entry.get("price_targets", entry.get("price", [])),
            "valuation_targets": raw_valuations if isinstance(raw_valuations, dict) else {},
        }
    return {"price_targets": [], "valuation_targets": {}}


def load_watchlist():
    try:
        with WATCHLIST_FILE.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except FileNotFoundError:
        print(f"Watchlist file not found: {WATCHLIST_FILE}")
        raise
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error loading {WATCHLIST_FILE}: {exc}")
        raise

    if not isinstance(raw, dict):
        raise ValueError("watchlist.json must contain an object keyed by ticker.")

    watchlist = {}
    # Normalize ticker names and merge duplicates rather than silently overwriting them.
    for raw_symbol, raw_entry in raw.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        entry = normalize_entry(raw_entry)
        combined = watchlist.setdefault(symbol, {"price_targets": [], "valuation_targets": {}})
        combined["price_targets"] = sorted(set(
            combined["price_targets"] + _positive_targets(entry.get("price_targets", []))
        ))
        for metric, targets in entry["valuation_targets"].items():
            if metric not in VALUATION_INFO_KEYS:
                continue
            current = combined["valuation_targets"].setdefault(metric, [])
            combined["valuation_targets"][metric] = sorted(set(current + _positive_targets(targets)))
    return watchlist


def _positive_targets(values):
    if not isinstance(values, (list, tuple, set)):
        return []
    result = []
    for value in values:
        number = _positive_number(value)
        if number is not None:
            result.append(number)
    return result


def save_watchlist(watchlist):
    """Persist target changes and let failures fail the GitHub Actions job."""
    with WATCHLIST_FILE.open("w", encoding="utf-8") as file:
        json.dump(watchlist, file, indent=2)
        file.write("\n")
    print("Updated watchlist.json saved successfully.")


def _post_embed(payload, alert_label):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing; target will be kept.")
        return False
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    except requests.RequestException as exc:
        print(f"Failed to send {alert_label} alert: {exc}; target will be kept.")
        return False

    if response.status_code in (200, 204):
        print(f"Discord notification sent successfully: {alert_label}.")
        return True

    print(
        f"Failed to send {alert_label} alert: HTTP {response.status_code}, "
        f"{getattr(response, 'text', '')}; target will be kept."
    )
    return False


def send_discord_alert(symbol, current_price, day_low, target_price):
    payload = {
        "username": "Stock Alerter",
        "embeds": [{
            "title": f"🚨 PRICE TARGET HIT: {symbol}",
            "color": 5763719,
            "fields": [
                {"name": "Target Price", "value": f"${target_price:.2f}", "inline": True},
                {"name": "Day's Low", "value": f"${day_low:.2f}", "inline": True},
                {"name": "Current Price", "value": f"${current_price:.2f}", "inline": True},
            ],
            "footer": {"text": "Target met today; target removed only after successful delivery"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }
    return _post_embed(payload, f"price target for {symbol}")


def send_valuation_alert(symbol, metric, current_value, target_value):
    labels = {"FxPE": "Forward P/E", "PE": "Trailing P/E", "P/S": "Price-to-Sales"}
    label = labels[metric]
    payload = {
        "username": "Stock Alerter",
        "embeds": [{
            "title": f"📈 VALUATION TARGET HIT: {symbol} ({metric})",
            "color": 15105570,
            "fields": [
                {"name": "Metric", "value": label, "inline": True},
                {"name": "Target", "value": f"{target_value:.1f}x", "inline": True},
                {"name": "Current", "value": f"{current_value:.1f}x", "inline": True},
            ],
            "description": f"{symbol} has reached or exceeded your {label} threshold.",
            "footer": {"text": "Target removed only after successful delivery"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }
    return _post_embed(payload, f"{metric} valuation target for {symbol}")


def _get_fast_info_value(fast_info, *names):
    for name in names:
        try:
            value = _positive_number(getattr(fast_info, name, None))
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def _get_valuation_snapshot(symbol):
    """Retrieve valuation multiples only for symbols with valuation targets."""
    try:
        info = yf.Ticker(symbol).get_info() or {}
    except Exception as exc:
        print(f"Warning: Could not fetch valuation data for {symbol}: {exc}; keeping valuation targets.")
        return {}
    return {metric: _positive_number(info.get(info_key)) for metric, info_key in VALUATION_INFO_KEYS.items()}


def check_prices():
    watchlist = load_watchlist()
    if not watchlist:
        print("No tickers found in watchlist.")
        return

    price_symbols = [symbol for symbol, entry in watchlist.items() if entry["price_targets"]]
    valuation_symbols = [symbol for symbol, entry in watchlist.items() if entry["valuation_targets"]]
    if not price_symbols and not valuation_symbols:
        print("No price or valuation targets to check.")
        return

    # Keep the existing batched fast-price lookup. Valuation data is fetched separately
    # only for symbols that actually have valuation targets.
    price_data = None
    if price_symbols:
        try:
            price_data = yf.Tickers(" ".join(price_symbols))
        except Exception as exc:
            print(f"Failed to initialize batch price data client: {exc}; price targets will be kept.")

    valuation_cache = {}
    modified = False
    updated_watchlist = {}

    for symbol, entry in watchlist.items():
        remaining_price_targets = list(entry["price_targets"])
        remaining_valuation_targets = {
            metric: list(targets)
            for metric, targets in entry["valuation_targets"].items()
            if metric in VALUATION_INFO_KEYS and targets
        }

        # Price targets: the intraday low triggers the existing downside threshold.
        if remaining_price_targets:
            if price_data is None:
                print(f"Warning: No price data client for {symbol}; keeping price targets.")
            else:
                try:
                    ticker_obj = price_data.tickers[symbol]
                    fast_info = ticker_obj.fast_info
                    current_price = _get_fast_info_value(fast_info, "last_price", "lastPrice")
                    day_low = _get_fast_info_value(fast_info, "day_low", "dayLow")
                    check_price = day_low if day_low is not None else current_price
                    if check_price is None:
                        print(f"Warning: Could not fetch valid price data for {symbol}; keeping price targets.")
                    else:
                        remaining_price_targets = []
                        for target in entry["price_targets"]:
                            if check_price <= target:
                                sent = send_discord_alert(
                                    symbol,
                                    current_price if current_price is not None else check_price,
                                    check_price,
                                    float(target),
                                )
                                if sent:
                                    modified = True
                                else:
                                    remaining_price_targets.append(target)
                            else:
                                remaining_price_targets.append(target)
                except Exception as exc:
                    print(f"Error processing price targets for {symbol}: {exc}; keeping price targets.")
                    remaining_price_targets = list(entry["price_targets"])

        # Valuation targets: for each metric, alert when the current multiple is at/above
        # the threshold. Missing data or failed Discord delivery never removes a target.
        if remaining_valuation_targets:
            if symbol not in valuation_cache:
                valuation_cache[symbol] = _get_valuation_snapshot(symbol)
            current_values = valuation_cache[symbol]
            for metric, targets in list(remaining_valuation_targets.items()):
                current_value = current_values.get(metric)
                if current_value is None:
                    print(f"Warning: {metric} unavailable for {symbol}; keeping {metric} targets.")
                    continue
                still_waiting = []
                for target in targets:
                    if current_value >= float(target):
                        if send_valuation_alert(symbol, metric, current_value, float(target)):
                            modified = True
                        else:
                            still_waiting.append(target)
                    else:
                        still_waiting.append(target)
                if still_waiting:
                    remaining_valuation_targets[metric] = still_waiting
                else:
                    remaining_valuation_targets.pop(metric, None)

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
    print("Checking stock price and valuation targets...")
    check_prices()
