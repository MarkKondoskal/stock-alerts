import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WATCHLIST_WEBHOOK") or os.environ.get("DISCORD_STOCK_WEBHOOK")

def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_watchlist(data):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print("Watchlist saved.")

def add_target(ticker, target):
    data = load_watchlist()
    targets = data.get(ticker, [])
    if target in targets:
        print(f"Target {target} already exists for {ticker}.")
        return
    targets.append(target)
    targets.sort()
    data[ticker] = targets
    save_watchlist(data)
    print(f"Added target {target} for {ticker}.")

def remove_target(ticker, target):
    data = load_watchlist()
    if ticker not in data:
        print(f"Ticker {ticker} not found in watchlist.")
        return
    targets = data[ticker]
    if target not in targets:
        print(f"Target {target} not found for {ticker}.")
        return
    targets.remove(target)
    if targets:
        data[ticker] = targets
    else:
        del data[ticker]
    save_watchlist(data)
    print(f"Removed target {target} for {ticker}.")

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
    for ticker, targets in sorted(data.items()):
        print(f"{ticker}: {', '.join(map(str, targets))}")

def send_watchlist_to_discord():
    data = load_watchlist()
    if not data:
        print("Watchlist is empty – nothing to send.")
        return

    if not DISCORD_WEBHOOK_URL:
        print("Error: No Discord webhook URL configured.")
        return

    # Build description: list of tickers and targets
    lines = []
    for ticker, targets in sorted(data.items()):
        targets_str = ", ".join(f"${t:.2f}" for t in targets)
        lines.append(f"**{ticker}** → {targets_str}")
    description = "\n".join(lines) if lines else "*No targets set.*"

    payload = {
        "username": "Watchlist Bot",
        "embeds": [
            {
                "title": "📋 Current Watchlist",
                "description": description,
                "color": 3447003,
                "footer": {"text": f"{len(data)} tickers monitored"},
                "timestamp": datetime.utcnow().isoformat()
            }
        ]
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        print("Watchlist sent to Discord.")
    except Exception as e:
        print(f"Failed to send watchlist: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python watchlist_manager.py ACTION [TICKER] [TARGET]")
        print("Actions: ADD, REMOVE, REMOVE_ALL, LIST, STATUS")
        sys.exit(1)

    action = sys.argv[1].upper()
    ticker = sys.argv[2].upper() if len(sys.argv) > 2 else None
    target = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None

    if action == "ADD":
        if not ticker or target is None:
            print("ADD requires both TICKER and TARGET.")
            sys.exit(1)
        add_target(ticker, target)
    elif action == "REMOVE":
        if not ticker or target is None:
            print("REMOVE requires both TICKER and TARGET.")
            sys.exit(1)
        remove_target(ticker, target)
    elif action == "REMOVE_ALL":
        if not ticker:
            print("REMOVE_ALL requires TICKER.")
            sys.exit(1)
        remove_all(ticker)
    elif action == "LIST":
        list_watchlist()
    elif action == "STATUS" or action == "SEND":
        send_watchlist_to_discord()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)

if __name__ == "__main__":
    main()
