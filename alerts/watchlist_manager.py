import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DISCORD_WEBHOOK_URL = (
    os.environ.get("DISCORD_WATCHLIST_WEBHOOK")
    or os.environ.get("DISCORD_STOCK_WEBHOOK")
)
METRIC_LABELS = {"PRICE": "PRICE", "FXPE": "FxPE", "PE": "PE", "P/S": "P/S"}
VALUATION_METRICS = ("FxPE", "PE", "P/S")
DESCRIPTION_LIMIT = 3500  # Leave room under Discord's 4096-character embed description limit.


def canonical_metric(metric):
    key = str(metric or "PRICE").strip().upper()
    if key not in METRIC_LABELS:
        raise ValueError(f"Unknown metric {metric!r}. Choose from PRICE, FxPE, PE, P/S.")
    return METRIC_LABELS[key]


def _valid_positive_numbers(values):
    result = []
    if not isinstance(values, (list, tuple, set)):
        return result
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            result.append(number)
    return sorted(set(result))


def _normalize_entry(entry):
    """Accept the original {ticker: [price targets]} format and the structured format."""
    if isinstance(entry, (list, tuple)):
        return {"price_targets": _valid_positive_numbers(entry), "valuation_targets": {}}
    if not isinstance(entry, dict):
        return {"price_targets": [], "valuation_targets": {}}

    price_values = entry.get("price_targets", entry.get("price", []))
    raw_valuations = entry.get("valuation_targets", entry.get("valuation", {}))
    normalized_valuations = {}
    if isinstance(raw_valuations, dict):
        for raw_metric, raw_values in raw_valuations.items():
            try:
                metric = canonical_metric(raw_metric)
            except ValueError:
                continue
            if metric == "PRICE":
                continue
            values = _valid_positive_numbers(raw_values)
            if values:
                normalized_valuations.setdefault(metric, []).extend(values)
    normalized_valuations = {
        metric: sorted(set(values))
        for metric, values in normalized_valuations.items() if values
    }
    return {
        "price_targets": _valid_positive_numbers(price_values),
        "valuation_targets": normalized_valuations,
    }


def load_watchlist():
    try:
        raw = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not load watchlist {WATCHLIST_FILE}: {exc}")
        raise

    result = {}
    if not isinstance(raw, dict):
        raise ValueError("watchlist.json must contain a JSON object keyed by ticker.")
    # Normalize symbols and merge duplicates (e.g. 'AVGO' and 'AVGO ').
    for raw_ticker, raw_entry in raw.items():
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        entry = _normalize_entry(raw_entry)
        combined = result.setdefault(ticker, {"price_targets": [], "valuation_targets": {}})
        combined["price_targets"] = sorted(set(combined["price_targets"] + entry["price_targets"]))
        for metric, values in entry["valuation_targets"].items():
            merged = combined["valuation_targets"].setdefault(metric, [])
            combined["valuation_targets"][metric] = sorted(set(merged + values))
    return result


def save_watchlist(data):
    WATCHLIST_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Watchlist saved.")


def add_target(ticker, target, metric="PRICE"):
    ticker = ticker.strip().upper()
    metric = canonical_metric(metric)
    target = float(target)
    if not ticker or not math.isfinite(target) or target <= 0:
        raise ValueError("Ticker and target must be valid; target must be positive.")

    data = load_watchlist()
    entry = data.setdefault(ticker, {"price_targets": [], "valuation_targets": {}})
    bucket = entry["price_targets"] if metric == "PRICE" else entry["valuation_targets"].setdefault(metric, [])
    if target in bucket:
        print(f"{metric} target {target:g} already exists for {ticker}.")
        return
    bucket.append(target)
    bucket.sort()
    save_watchlist(data)
    print(f"Added {metric} target {target:g} for {ticker}.")


def remove_target(ticker, target, metric="PRICE"):
    ticker = ticker.strip().upper()
    metric = canonical_metric(metric)
    target = float(target)
    data = load_watchlist()
    if ticker not in data:
        print(f"Ticker {ticker} not found in watchlist.")
        return

    entry = data[ticker]
    bucket = entry["price_targets"] if metric == "PRICE" else entry["valuation_targets"].get(metric, [])
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
    ticker = ticker.strip().upper()
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
        parts = [f"PRICE: {entry['price_targets']} "] if entry["price_targets"] else []
        parts.extend(f"{metric}: {values}" for metric, values in sorted(entry["valuation_targets"].items()))
        print(f"{ticker}: " + ("; ".join(parts) if parts else "no targets"))


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def get_market_snapshot(ticker):
    """Fetch price and all three valuation metrics from one ticker info response where possible."""
    price = None
    valuations = {metric: None for metric in VALUATION_METRICS}
    stock = yf.Ticker(ticker)
    info = {}
    try:
        info = stock.get_info() or {}
    except Exception as exc:
        print(f"Could not fetch valuation/quote info for {ticker}: {exc}")

    # Yahoo's info response normally includes both current price and these valuation fields.
    price = _positive_number(info.get("currentPrice")) or _positive_number(info.get("regularMarketPrice"))
    valuations = {
        "FxPE": _positive_number(info.get("forwardPE")),
        "PE": _positive_number(info.get("trailingPE")),
        "P/S": _positive_number(info.get("priceToSalesTrailing12Months")),
    }

    # Fall back to fast_info only when get_info did not supply a usable price.
    if price is None:
        try:
            fast_info = stock.fast_info
            price = _positive_number(getattr(fast_info, "last_price", None)) or _positive_number(
                getattr(fast_info, "lastPrice", None)
            )
        except Exception as exc:
            print(f"Could not fetch live price for {ticker}: {exc}")

    return (round(price, 2) if price is not None else None), valuations


def format_valuations(valuations):
    parts = []
    for metric in VALUATION_METRICS:
        value = valuations.get(metric)
        parts.append(f"{metric}: {value:.1f}x" if value is not None else f"{metric}: —")
    return " · ".join(parts)


def _make_embeds(rows, ticker_count):
    """Build an aligned, monospaced table while keeping all tickers in one webhook post."""
    headers = ["Ticker", "Current", "Targets", "FxPE", "PE", "P/S"]
    widths = [
        max(len(headers[i]), *(len(str(row[i])) for row in rows))
        for i in range(len(headers))
    ]

    def format_line(values):
        return " | ".join(str(value).ljust(widths[i]) for i, value in enumerate(values)).rstrip()

    header_line = format_line(headers)
    separator_line = "-+-".join("-" * width for width in widths)
    formatted_rows = [format_line(row) for row in rows]
    prefix = "**Watchlist with live prices and valuations**\nTargets include price levels and valuation triggers.\n\n" 
    descriptions = []
    current_rows = []

    def build_table(table_rows):
        lines = [header_line, separator_line, *table_rows]
        return "```text\n" + "\n".join(lines) + "\n```"

    # Keep a single table per embed; if Discord's description limit is reached,
    # continuation embeds are attached to the same webhook message.
    for line in formatted_rows:
        candidate_rows = current_rows + [line]
        candidate_prefix = prefix if not descriptions else ""
        candidate = candidate_prefix + build_table(candidate_rows)
        if current_rows and len(candidate) > DESCRIPTION_LIMIT:
            descriptions.append((prefix if not descriptions else "") + build_table(current_rows))
            current_rows = [line]
        else:
            current_rows = candidate_rows

    if current_rows or not descriptions:
        descriptions.append((prefix if not descriptions else "") + build_table(current_rows))

    embeds = []
    for index, description in enumerate(descriptions):
        title = "📋 Current Watchlist" if index == 0 else "📋 Current Watchlist (continued)"
        embeds.append({
            "title": title,
            "description": description,
            "color": 3447003,
            "footer": {"text": f"{ticker_count} tickers monitored · Part {index + 1}/{len(descriptions)}"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return embeds


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
        target_parts = [f"${target:.2f}" for target in entry["price_targets"]]
        for metric in VALUATION_METRICS:
            for target in entry["valuation_targets"].get(metric, []):
                target_parts.append(f"{metric}≥{target:g}x")
        targets_str = ", ".join(target_parts) if target_parts else "—"

        current_price, valuations = get_market_snapshot(ticker)
        current_str = f"${current_price:.2f}" if current_price is not None else "N/A"
        valuation_cells = [
            f"{valuations[metric]:.1f}x" if valuations.get(metric) is not None else "—"
            for metric in VALUATION_METRICS
        ]
        rows.append([ticker, current_str, targets_str, *valuation_cells])

    payload = {"username": "Watchlist Bot", "embeds": _make_embeds(rows, len(data))}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
        response.raise_for_status()
        print("Watchlist with prices and valuations sent to Discord.")
    except Exception as exc:
        print(f"Failed to send watchlist: {exc}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python watchlist_manager.py ACTION [TICKER] [TARGET] [METRIC]")
        sys.exit(1)
    action = sys.argv[1].strip().upper()
    ticker = sys.argv[2].strip().upper() if len(sys.argv) > 2 and sys.argv[2] else None
    try:
        target = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
        metric = canonical_metric(sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else "PRICE")
    except ValueError as exc:
        print(f"Invalid input: {exc}")
        sys.exit(2)

    if action == "ADD":
        if not ticker or target is None:
            print("ADD requires TICKER and TARGET.")
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
