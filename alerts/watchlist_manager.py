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
