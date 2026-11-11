from datetime import datetime, timezone
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watchlist_rules import validate_watchlist
from alerts.alert_history import deliver

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
WATCHLIST_FILE = os.environ.get("STOCKALERTS_WATCHLIST_FILE") or os.path.join(BASE_DIR, "watchlist.json")


def load_watchlist():
    # A missing or invalid watchlist is a workflow failure, not an empty watchlist:
    # silently returning {} would mask configuration mistakes and lost alerts.
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("watchlist.json must contain an object keyed by ticker")
    return validate_watchlist(raw)


def save_watchlist(watchlist):
    # Write atomically; if persisting successful deliveries fails, make the job
    # red rather than silently repeating those notifications in the next run.
    from pathlib import Path
    import tempfile

    destination = Path(WATCHLIST_FILE)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                         prefix=".watchlist-", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            json.dump(watchlist, f, indent=2)
            f.write("\n")
        os.replace(temp_path, destination)
        print("Updated watchlist.json saved successfully.")
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def send_discord_alert(symbol, current_price, day_low, target_price):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing.")
        return False
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
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    except requests.RequestException as exc:
        # Return False instead of raising: an exception here would abort the whole
        # symbol and keep targets that were already delivered (duplicate alerts).
        print(f"Failed to send alert for {symbol}: {exc}")
        return False
    if response.status_code not in [200, 204]:
        print(f"Failed to send alert: {response.status_code}, {response.text}")
        return False
    print(f"Discord notification sent successfully for {symbol}.")
    return True



def send_valuation_alert(symbol, metric, direction, target, actual, current_price):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_STOCK_WEBHOOK environment variable is missing.")
        return False
    is_trim = direction == "trim"
    title = f"📈 VALUATION TRIM TARGET: {symbol}" if is_trim else f"🎯 VALUATION BUY ZONE: {symbol}"
    comparator = "≥" if is_trim else "≤"
    payload = {"username": "Stock Alerter", "embeds": [{
        "title": title,
        "color": 15158332 if is_trim else 3066993,
        "fields": [
            {"name": "Metric", "value": metric, "inline": True},
            {"name": "Target", "value": f"{comparator} {target:g}x", "inline": True},
            {"name": "Current multiple", "value": f"{actual:.2f}x", "inline": True},
            {"name": "Share price", "value": f"${current_price:.2f}" if current_price else "N/A", "inline": True},
        ],
        "footer": {"text": "Triggered target removed after successful delivery"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }]}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code not in (200, 204):
            print(f"Failed to send valuation alert: {response.status_code}, {response.text}")
            return False
        print(f"Valuation alert sent: {symbol} {metric} {direction} {target:g}x")
        return True
    except requests.RequestException as exc:
        print(f"Failed to send valuation alert: {exc}")
        return False


def _positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def _metric_value(info, metric):
    keys = {"FxPE": "forwardPE", "PE": "trailingPE", "P/S": "priceToSalesTrailing12Months"}
    return _positive_number(info.get(keys[metric]))

def session_prices(ticker, now=None):
    """Only a complete exchange-local daily bar for today can trigger a price alert."""
    now = now or datetime.now(timezone.utc)
    history = ticker.history(period='5d', interval='1d', auto_adjust=False)
    if history is None or history.empty:
        raise ValueError('No dated price observations available')
    stamp = history.index[-1]
    if stamp.tzinfo is None:
        raise ValueError('Quote has no exchange timezone')
    if stamp.date() == now.astimezone(stamp.tzinfo).date():
        row = history.iloc[-1]
        current, low = _positive_number(row['Close']), _positive_number(row['Low'])
        if current is not None and low is not None:
            return current, low

    regular = ticker.get_history_metadata().get('currentTradingPeriod', {}).get('regular', {})
    start, end = _positive_number(regular.get('start')), _positive_number(regular.get('end'))
    if start is not None and end is not None and start < end:
        if not start <= now.timestamp() < end:
            return None, None
    raise ValueError('Current session quote is incomplete or regular hours are unavailable')


def check_prices():
    watchlist = load_watchlist()
    if not watchlist:
        print("No targets to check.")
        return True

    # Check tickers with either price or valuation targets.
    symbols = [symbol for symbol, entry in watchlist.items()
               if entry["price_targets"] or entry["valuation_targets"]]
    if not symbols:
        print("No active price or valuation targets to check.")
        try:
            return _positive_number(yf.Ticker('SPY').fast_info.last_price) is not None
        except Exception:
            return False

    try:
        data = yf.Tickers(" ".join(symbols))
    except Exception as exc:
        raise RuntimeError(f"Failed to initialize market data client: {exc}") from exc

    updated = {}
    changed = False
    complete = True
    for symbol, entry in watchlist.items():
        price_targets = list(entry["price_targets"])
        valuation_targets = entry["valuation_targets"]
        if not price_targets and not valuation_targets:
            updated[symbol] = entry
            continue
        delivered_prices = []  # price targets Discord has already accepted
        try:
            ticker = data.tickers[symbol]
            current_price, day_low = session_prices(ticker)
            if price_targets and current_price is None:
                print(f"{symbol}: price check skipped outside regular hours; target kept for the next run.")
            check_price = day_low or current_price
            remaining_prices = []
            for target in price_targets:
                if check_price is not None and check_price <= target:
                    if deliver(lambda: send_discord_alert(symbol, float(current_price or check_price), float(check_price), float(target)),
                               ticker=symbol, metric='PRICE', direction='buy', target=float(target), actual=float(check_price)):
                        changed = True
                        delivered_prices.append(target)
                    else:
                        complete = False
                        remaining_prices.append(target)
                else:
                    remaining_prices.append(target)

            remaining_valuations = {}
            if valuation_targets:
                try:
                    info = ticker.get_info() or {}
                except Exception as exc:
                    print(f"Could not fetch valuation data for {symbol}; keeping valuation targets: {exc}")
                    complete = False
                    info = None
                for metric, raw_targets in valuation_targets.items():
                    # Legacy lists mean trim thresholds.
                    if isinstance(raw_targets, list):
                        targets = {"trim": raw_targets, "buy": []}
                    else:
                        targets = raw_targets if isinstance(raw_targets, dict) else {"trim": [], "buy": []}
                    actual = _metric_value(info, metric) if info is not None else None
                    keep = {"trim": [], "buy": []}
                    for direction in ("trim", "buy"):
                        for target in targets.get(direction, []):
                            triggered = actual is not None and ((direction == "trim" and actual >= target) or (direction == "buy" and actual <= target))
                            if triggered:
                                if deliver(lambda: send_valuation_alert(symbol, metric, direction, float(target), float(actual), current_price),
                                           ticker=symbol, metric=metric, direction=direction, target=float(target), actual=float(actual)):
                                    changed = True
                                else:
                                    complete = False
                                    keep[direction].append(target)
                            else:
                                keep[direction].append(target)
                    if keep["trim"] or keep["buy"]:
                        remaining_valuations[metric] = keep
            if remaining_prices or remaining_valuations:
                updated[symbol] = {"price_targets": remaining_prices, "valuation_targets": remaining_valuations}
        except Exception as exc:
            complete = False
            print(f"Error processing {symbol}; preserving undelivered targets: {exc}")
            # Drop only the price targets that were already delivered so they are
            # not sent again; everything else (including unprocessed targets) stays.
            if delivered_prices:
                changed = True
            leftover = [t for t in price_targets if t not in delivered_prices]
            if leftover or valuation_targets:
                updated[symbol] = {"price_targets": leftover,
                                   "valuation_targets": valuation_targets}

    if changed:
        save_watchlist(updated)
    return complete


if __name__ == "__main__":
    print("Checking stock prices...")
    raise SystemExit(0 if check_prices() else 1)
