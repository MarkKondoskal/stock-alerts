import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watchlist_rules import validate_watchlist, ticker_symbol, positive_target

import json
import math
import os
from datetime import datetime, timezone

import requests
import yfinance as yf

WATCHLIST_FILE = Path(os.environ["STOCKALERTS_WATCHLIST_FILE"]) if os.environ.get("STOCKALERTS_WATCHLIST_FILE") else Path(__file__).with_name("watchlist.json")
DISCORD_WEBHOOK_URL = (
    os.environ.get("DISCORD_WATCHLIST_WEBHOOK")
    or os.environ.get("DISCORD_STOCK_WEBHOOK")
)
METRIC_LABELS = {"PRICE": "PRICE", "FXPE": "FxPE", "PE": "PE", "P/S": "P/S"}
VALUATION_METRICS = ("FxPE", "PE", "P/S")
DISPLAY_METRICS = ("PE", "FxPE", "P/S")
DESCRIPTION_LIMIT = 3500  # Leave room under Discord's 4096-character embed description limit.


def canonical_metric(metric):
    key = str(metric or "PRICE").strip().upper()
    if key not in METRIC_LABELS:
        raise ValueError(f"Unknown metric {metric!r}. Choose from PRICE, FxPE, PE, P/S.")
    return METRIC_LABELS[key]


def load_watchlist():
    try:
        raw = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not load watchlist {WATCHLIST_FILE}: {exc}")
        raise

    return validate_watchlist(raw)


def save_watchlist(data):
    WATCHLIST_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Watchlist saved.")


def add_target(ticker, target, metric="PRICE", direction="trim"):
    ticker = ticker_symbol(ticker)
    metric = canonical_metric(metric)
    target = positive_target(target)
    if not ticker or not math.isfinite(target) or target <= 0:
        raise ValueError("Ticker and target must be valid; target must be positive.")

    data = load_watchlist()
    entry = data.setdefault(ticker, {"price_targets": [], "valuation_targets": {}})
    direction = str(direction or "trim").strip().lower()
    if direction not in ("trim", "buy"):
        raise ValueError("Direction must be TRIM or BUY.")
    if metric == "PRICE":
        bucket = entry["price_targets"]
    else:
        metric_targets = entry["valuation_targets"].setdefault(metric, {"trim": [], "buy": []})
        # Accept any legacy shape still present in memory.
        if isinstance(metric_targets, list):
            metric_targets = {"trim": metric_targets, "buy": []}
            entry["valuation_targets"][metric] = metric_targets
        bucket = metric_targets[direction]
    if target in bucket:
        print(f"{metric} target {target:g} already exists for {ticker}.")
        return
    bucket.append(target)
    bucket.sort()
    save_watchlist(data)
    print(f"Added {metric} {direction.upper()} target {target:g} for {ticker}.")


def remove_target(ticker, target, metric="PRICE", direction="trim"):
    ticker = ticker_symbol(ticker)
    metric = canonical_metric(metric)
    target = positive_target(target)
    data = load_watchlist()
    if ticker not in data:
        print(f"Ticker {ticker} not found in watchlist.")
        return

    entry = data[ticker]
    direction = str(direction or "trim").strip().lower()
    if direction not in ("trim", "buy"):
        raise ValueError("Direction must be TRIM or BUY.")
    if metric == "PRICE":
        bucket = entry["price_targets"]
    else:
        metric_targets = entry["valuation_targets"].get(metric, {"trim": [], "buy": []})
        if isinstance(metric_targets, list):
            metric_targets = {"trim": metric_targets, "buy": []}
            entry["valuation_targets"][metric] = metric_targets
        bucket = metric_targets[direction]
    if target not in bucket:
        print(f"{metric} target {target:g} not found for {ticker}.")
        return
    bucket.remove(target)
    if metric != "PRICE":
        metric_targets = entry["valuation_targets"].get(metric, {})
        if not metric_targets.get("trim") and not metric_targets.get("buy"):
            entry["valuation_targets"].pop(metric, None)
    if not entry["price_targets"] and not entry["valuation_targets"]:
        del data[ticker]
    save_watchlist(data)
    print(f"Removed {metric} {direction.upper()} target {target:g} for {ticker}.")


def remove_all(ticker):
    ticker = ticker_symbol(ticker)
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
        for metric, directions in sorted(entry["valuation_targets"].items()):
            if isinstance(directions, list):
                directions = {"trim": directions, "buy": []}
            if directions.get("trim"):
                parts.append(f"{metric} TRIM (≥): {directions['trim']}")
            if directions.get("buy"):
                parts.append(f"{metric} BUY (≤): {directions['buy']}")
        print(f"{ticker}: " + ("; ".join(parts) if parts else "no targets"))


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def get_market_snapshot(ticker):
    """Fetch price, valuation multiples and YoY revenue growth from one info response."""
    stock = yf.Ticker(ticker)
    info = {}
    try:
        info = stock.get_info() or {}
    except Exception as exc:
        print(f"Could not fetch valuation/quote info for {ticker}: {exc}")

    price = _positive_number(info.get("currentPrice")) or _positive_number(info.get("regularMarketPrice"))
    valuations = {
        "FxPE": _positive_number(info.get("forwardPE")),
        "PE": _positive_number(info.get("trailingPE")),
        "P/S": _positive_number(info.get("priceToSalesTrailing12Months")),
    }

    # yfinance/Yahoo provides revenueGrowth as a decimal ratio (e.g. 0.12 = +12%).
    revenue_growth_pct = None
    try:
        raw_growth = float(info.get("revenueGrowth"))
        if math.isfinite(raw_growth):
            revenue_growth_pct = round(raw_growth * 100, 1)
    except (TypeError, ValueError):
        pass

    # Fall back to fast_info only when get_info did not supply a usable price.
    if price is None:
        try:
            fast_info = stock.fast_info
            price = _positive_number(getattr(fast_info, "last_price", None)) or _positive_number(
                getattr(fast_info, "lastPrice", None)
            )
        except Exception as exc:
            print(f"Could not fetch live price for {ticker}: {exc}")

    return (round(price, 2) if price is not None else None), valuations, revenue_growth_pct


def _format_price_target(target):
    """Keep target cells compact without losing meaningful cents when present."""
    value = f"{target:.2f}".rstrip("0").rstrip(".")
    return f"${value}"


def _make_embeds(rows, ticker_count, target_details=None):
    """Narrow one-line-per-ticker table, with full target details retained below.

    Discord's monospaced code blocks wrap on narrow/mobile clients; limit the
    width instead of relying on seven spacious, pipe-separated columns.
    """
    target_details = target_details or []
    headers = ('Ticker', 'Price', 'Targets', 'P/E', 'FPE', 'P/S', 'YoY')
    widths = (10, 8, 10, 6, 6, 6, 8)

    def row_line(cells):
        return ' '.join(str(cell)[:width].ljust(width) for cell, width in zip(cells, widths)).rstrip()

    header = row_line(headers)
    lines = [row_line(row) for row in rows]
    descriptions = []
    current = []
    prefix = '**Watchlist · price, valuation and growth**\n' \
             'FPE = forward P/E · YoY = revenue growth\n\n'

    def block(chunk):
        return '```text\n' + '\n'.join([header, *chunk]) + '\n```'

    for line in lines:
        candidate = current + [line]
        proposed = (prefix if not descriptions else '') + block(candidate)
        if current and len(proposed) > DESCRIPTION_LIMIT:
            descriptions.append((prefix if not descriptions else '') + block(current))
            current = [line]
        else:
            current = candidate
    if current or not descriptions:
        descriptions.append((prefix if not descriptions else '') + block(current))

    # Full target rules are kept separate instead of widening every table row.
    if target_details:
        note = ''
        for detail in target_details:
            if note and len(note) + len(detail) + 1 > DESCRIPTION_LIMIT:
                descriptions.append('**Complete target rules**\n' + note)
                note = ''
            note += detail + '\n'
        if note:
            descriptions.append('**Complete target rules**\n' + note)

    # A Discord webhook may include at most 10 embeds. Beyond that, fail
    # explicitly instead of posting a truncated/incomplete watchlist.
    if len(descriptions) > 10:
        raise ValueError('Watchlist exceeds Discord 10-embed limit; reduce entries or split the post')
    return [{
        'title': '📋 Current Watchlist' if i == 0 else '📋 Current Watchlist (continued)',
        'description': description,
        'color': 3447003,
        'footer': {'text': f'{ticker_count} tickers · Part {i + 1}/{len(descriptions)}'},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    } for i, description in enumerate(descriptions)]


def _compact_targets(targets, max_len=10):
    """Table abbreviation; full target list is printed separately when needed."""
    if not targets:
        return '—'
    joined = ','.join(targets)
    if len(joined) <= max_len:
        return joined
    first = targets[0]
    short = f'{first[:max_len-4]}+{len(targets)-1}'
    return short[:max_len]


def send_watchlist_to_discord():
    """Post the watchlist table. Returns True only if Discord accepted it."""
    data = load_watchlist()
    if not data:
        print("Watchlist is empty – no Discord status was sent.")
        return False
    if not DISCORD_WEBHOOK_URL:
        print("Error: No Discord webhook URL configured.")
        return False

    rows = []
    details = []
    for ticker in sorted(data):
        entry = data[ticker]
        target_parts = [_format_price_target(target) for target in entry["price_targets"]]
        for metric in VALUATION_METRICS:
            metric_targets = entry["valuation_targets"].get(metric, {"trim": [], "buy": []})
            if isinstance(metric_targets, list):
                metric_targets = {"trim": metric_targets, "buy": []}
            for target in metric_targets.get("trim", []):
                target_parts.append(f"{metric} trim≥{target:g}x")
            for target in metric_targets.get("buy", []):
                target_parts.append(f"{metric} buy≤{target:g}x")
        targets_str = ", ".join(target_parts) if target_parts else "—"

        current_price, valuations, revenue_growth_pct = get_market_snapshot(ticker)
        current_str = f"${current_price:.2f}" if current_price is not None else "N/A"
        valuation_cells = [
            f"{valuations[metric]:.1f}x" if valuations.get(metric) is not None else "—"
            for metric in DISPLAY_METRICS
        ]
        growth_cell = f"{revenue_growth_pct:+.1f}%" if revenue_growth_pct is not None else "—"
        price_target_strings = [_format_price_target(x) for x in entry['price_targets']]
        compact = _compact_targets(price_target_strings)
        if len(targets_str) > 10 or any(entry['valuation_targets'].values()):
            details.append(f'`{ticker}` · {targets_str}')
        rows.append([ticker, current_str, compact, *valuation_cells, growth_cell])

    payload = {"username": "Watchlist Bot", "embeds": _make_embeds(rows, len(data), details)}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
        response.raise_for_status()
        print("Watchlist with prices, valuations and revenue growth sent to Discord.")
        return True
    except Exception as exc:
        print(f"Failed to send watchlist: {exc}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python watchlist_manager.py ACTION [TICKER] [TARGET] [METRIC] [DIRECTION]")
        sys.exit(1)
    action = sys.argv[1].strip().upper()
    ticker = sys.argv[2].strip().upper() if len(sys.argv) > 2 and sys.argv[2] else None
    try:
        target = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
        metric = canonical_metric(sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else "PRICE")
        direction = (sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else "TRIM").strip().lower()
        if direction not in ("trim", "buy"):
            raise ValueError("Direction must be TRIM or BUY.")
    except ValueError as exc:
        print(f"Invalid input: {exc}")
        sys.exit(2)

    if action == "ADD":
        if not ticker or target is None:
            print("ADD requires TICKER and TARGET.")
            sys.exit(1)
        add_target(ticker, target, metric, direction)
    elif action == "REMOVE":
        if not ticker or target is None:
            print("REMOVE requires TICKER and TARGET.")
            sys.exit(1)
        remove_target(ticker, target, metric, direction)
    elif action == "REMOVE_ALL":
        if not ticker:
            print("REMOVE_ALL requires TICKER.")
            sys.exit(1)
        remove_all(ticker)
    elif action == "LIST":
        list_watchlist()
    elif action in ("STATUS", "SEND"):
        if not send_watchlist_to_discord():
            # Non-zero exit makes the GitHub Actions run show as failed.
            sys.exit(1)
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
