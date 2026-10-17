import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WATCHLIST_WEBHOOK") or os.environ.get("DISCORD_STOCK_WEBHOOK")
METRICS = {"PRICE", "FxPE", "PE", "P/S"}


def _normalize_entry(entry):
    """Accept the old list format as well as the current structured format."""
    if isinstance(entry, list):
        return {"price_targets": [float(x) for x in entry], "valuation_targets": {}}
    if not isinstance(entry, dict):
        return {"price_targets": [], "valuation_targets": {}}
    price = entry.get("price_targets", entry.get("price", []))
    valuation = entry.get("valuation_targets", entry.get("valuation", {}))
    return {
        "price_targets": sorted(set(float(x) for x in price)),
        "valuation_targets": {
            str(metric): sorted(set(float(x) for x in values))
            for metric, values in valuation.items() if values
        },
    }


def load_watchlist():
    try:
        raw = json.loads(WATCHLIST_FILE.read_text())
    except FileNotFoundError:
        return {}
    return {str(ticker).strip().upper(): _normalize_entry(entry)
            for ticker, entry in raw.items() if str(ticker).strip()}


def save_watchlist(data):
    WATCHLIST_FILE.write_text(json.dumps(data, indent=2) + "\n")
    print("Watchlist saved.")


def add_target(ticker, target, metric="PRICE"):
    metric = metric if metric == "PRICE" else metric.upper() if metric.upper() == "PE" else metric
    if metric not in METRICS:
        raise ValueError(f"Unknown metric {metric}. Choose from {', '.join(sorted(METRICS))}.")
    data = load_watchlist()
    entry = data.setdefault(ticker, {"price_targets": [], "valuation_targets": {}})
    bucket = entry["price_targets"] if metric == "PRICE" else entry["valuation_targets"].setdefault(metric, [])
    target = float(target)
    if target in bucket:
        print(f"{metric} target {target:g} already exists for {ticker}.")
        return
    bucket.append(target)
    bucket.sort()
    save_watchlist(data)
    print(f"Added {metric} target {target:g} for {ticker}.")


def remove_target(ticker, target, metric="PRICE"):
    data = load_watchlist()
    if ticker not in data:
        print(f"Ticker {ticker} not found in watchlist.")
        return
    entry = data[ticker]
    bucket = entry["price_targets"] if metric == "PRICE" else entry["valuation_targets"].get(metric, [])
    target = float(target)
    if target not in bucket:
        print(f"{metric} target {target:g} not found for {ticker}.")
        return
    bucket.remove(target)
    if metric != "PRICE" and not bucket:
        entry["valuation_targets"].pop(metric, None)
    if not entry["price_targets"] and not entry["valuation_targets"]:
        del data[ticker]
    save_watchlist(data)
    print(f"Removed {metric} target {target:g} for {ticker}.")


def remove_all(ticker):
    data = load_watchlist()
    if ticker not in data:
        print(f"Ticker {ticker} not found.")
        return
    del data[ticker]
    save_watchlist(data)
    print(f"Removed all targets for {ticker}.")


def list_watchlist():
    data = load_watchlist()
    if not data:
        print("Watchlist is empty.")
        return
    for ticker, entry in sorted(data.items()):
        parts = [f"PRICE: {entry['price_targets']}" ] if entry["price_targets"] else []
        parts.extend(f"{metric}: {values}" for metric, values in sorted(entry["valuation_targets"].items()))
        print(f"{ticker}: " + ("; ".join(parts) if parts else "no targets"))


def get_current_price(ticker):
    try:
        fast_info = yf.Ticker(ticker).fast_info
        price = getattr(fast_info, "last_price", None) or getattr(fast_info, "lastPrice", None)
        if price is not None and float(price) > 0:
            return round(float(price), 2)
    except Exception as exc:
        print(f"Could not fetch price for {ticker}: {exc}")
    return None


def get_current_valuations(ticker):
    """Fetch valuation data only for tickers with valuation targets, limiting Yahoo requests."""
    try:
        info = yf.Ticker(ticker).get_info()
        values = {
            "FxPE": info.get("forwardPE"),
            "PE": info.get("trailingPE"),
            "P/S": info.get("priceToSalesTrailing12Months"),
        }
        return {k: float(v) for k, v in values.items()
                if isinstance(v, (int, float)) and v > 0}
    except Exception as exc:
        print(f"Could not fetch valuation data for {ticker}: {exc}")
        return {}


def send_watchlist_to_discord():
    data = load_watchlist()
    if not data:
        print("Watchlist is empty – nothing to send.")
        return
    if not DISCORD_WEBHOOK_URL:
        print("Error: No Discord webhook URL configured.")
        return

    rows = []
    for ticker in sorted(data):
        entry = data[ticker]
        targets = [f"${x:.2f}" for x in entry["price_targets"]]
        for metric, values in sorted(entry["valuation_targets"].items()):
            targets.extend(f"{metric} {x:g}x" if metric != "P/S" else f"P/S {x:g}x" for x in values)
        targets_str = ", ".join(targets) if targets else "—"
        current_price = get_current_price(ticker)
        current_str = f"${current_price:.2f}" if current_price is not None else "N/A"

        valuation_str = "—"
        if entry["valuation_targets"]:
            valuations = get_current_valuations(ticker)
            labels = {"FxPE": "FxPE", "PE": "PE", "P/S": "P/S"}
            valuation_str = " · ".join(
                f"{labels[m]}: {valuations[m]:.1f}x" if m in valuations else f"{labels[m]}: N/A"
                for m in ("FxPE", "PE", "P/S")
            )
        rows.append(f"| {ticker} | {current_str} | {targets_str} | {valuation_str} |")

    table_header = "| Ticker | Current | Targets | Valuation |\n|--------|---------|---------|-----------|"
    table = table_header + "\n" + "\n".join(rows)
    description = f"**Watchlist with live prices**\n\n{table}"
    payload = {
        "username": "Watchlist Bot",
        "embeds": [{
            "title": "📋 Current Watchlist",
            "description": description,
            "color": 3447003,
            "footer": {"text": f"{len(data)} tickers monitored"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        response.raise_for_status()
        print("Watchlist sent to Discord.")
    except Exception as exc:
        print(f"Failed to send watchlist: {exc}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python watchlist_manager.py ACTION [TICKER] [TARGET] [METRIC]")
        sys.exit(1)
    action = sys.argv[1].upper()
    ticker = sys.argv[2].strip().upper() if len(sys.argv) > 2 and sys.argv[2] else None
    target = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
    metric = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else "PRICE"
    if metric not in METRICS:
        print(f"Invalid metric {metric}. Choose from {', '.join(sorted(METRICS))}.")
        sys.exit(1)

    if action == "ADD":
        if not ticker or target is None or target <= 0:
            print("ADD requires TICKER and a positive TARGET.")
            sys.exit(1)
        add_target(ticker, target, metric)
    elif action == "REMOVE":
        if not ticker or target is None:
            print("REMOVE requires TICKER and TARGET.")
            sys.exit(1)
        remove_target(ticker, target, metric)
    elif action == "REMOVE_ALL":
        if not ticker:
            print("REMOVE_ALL requires TICKER.")
            sys.exit(1)
        remove_all(ticker)
    elif action == "LIST":
        list_watchlist()
    elif action in ("STATUS", "SEND"):
        send_watchlist_to_discord()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
