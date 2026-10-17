import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

from sector_classifier import GROUP_ORDER, get_group, normalize_ticker, _load_json, _save_json, OVERRIDES_FILE

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DISCORD_WEBHOOK_URL = (
    os.environ.get("DISCORD_WATCHLIST_WEBHOOK")
    or os.environ.get("DISCORD_STOCK_WEBHOOK")
)


def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {"stocks": {}, "research": {}}
    except Exception as e:
        print(f"Error loading watchlist: {e}")
        return {"stocks": {}, "research": {}}

    if isinstance(raw, dict) and "stocks" in raw:
        stocks = raw.get("stocks", {}) or {}
        research = raw.get("research", {}) or {}
    else:
        stocks = {str(t).strip().upper(): {"targets": targets} for t, targets in (raw or {}).items()}
        research = {}

    normalized_stocks = {}
    for ticker, config in stocks.items():
        ticker = normalize_ticker(ticker)
        if not ticker:
            continue
        targets = config.get("targets", []) if isinstance(config, dict) else config
        normalized_stocks[ticker] = {
            "targets": sorted({float(t) for t in (targets or [])}),
            "valuation_targets": list(config.get("valuation_targets", [])) if isinstance(config, dict) else [],
        }

    normalized_research = {}
    for ticker, config in research.items():
        ticker = normalize_ticker(ticker)
        if not ticker:
            continue
        config = config if isinstance(config, dict) else {}
        normalized_research[ticker] = {"notes": str(config.get("notes", "")).strip()}

    return {"stocks": normalized_stocks, "research": normalized_research}


def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Watchlist saved.")


def add_target(ticker, target):
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    config = data["stocks"].get(ticker, {"targets": []})
    targets = config.get("targets", [])

    if target in targets:
        print(f"Target {target} already exists for {ticker}.")
        return

    targets.append(float(target))
    config = {"targets": sorted(set(targets)), "valuation_targets": list(config.get("valuation_targets", []))}
    data["stocks"][ticker] = config
    data["research"].pop(ticker, None)
    save_watchlist(data)
    print(f"Added target {target} for {ticker}.")
    print(f"Automatic group: {get_group(ticker)}")


def add_valuation_target(ticker, metric, threshold, direction="TRIM"):
    """Add a valuation-multiple alert, e.g. forward P/E >= 35x to trim."""
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    aliases = {"PE": "pe", "P/E": "pe", "TRAILING PE": "pe", "FORWARD PE": "forward_pe",
               "FORWARD P/E": "forward_pe", "FORWARD_PE": "forward_pe", "P/S": "ps", "PS": "ps"}
    metric = aliases.get(str(metric).strip().upper(), str(metric).strip().lower())
    direction = str(direction).strip().upper()
    if metric not in {"pe", "forward_pe", "ps"}:
        raise ValueError("Metric must be pe, forward_pe, or ps.")
    if direction not in {"ADD", "TRIM"}:
        raise ValueError("Direction must be ADD or TRIM.")
    threshold = float(threshold)
    config = data["stocks"].setdefault(ticker, {"targets": [], "valuation_targets": []})
    config.setdefault("targets", [])
    config.setdefault("valuation_targets", [])
    item = {"metric": metric, "direction": direction, "target": threshold}
    if item not in config["valuation_targets"]:
        config["valuation_targets"].append(item)
    config["valuation_targets"].sort(key=lambda x: (x.get("metric", ""), x.get("target", 0)))
    data["research"].pop(ticker, None)
    save_watchlist(data)
    print(f"Added {direction} valuation target for {ticker}: {metric} {threshold:g}x")
    print(f"Automatic group: {get_group(ticker)}")


def remove_valuation_target(ticker, metric, threshold, direction="TRIM"):
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    aliases = {"PE": "pe", "P/E": "pe", "TRAILING PE": "pe", "FORWARD PE": "forward_pe",
               "FORWARD P/E": "forward_pe", "FORWARD_PE": "forward_pe", "P/S": "ps", "PS": "ps"}
    metric = aliases.get(str(metric).strip().upper(), str(metric).strip().lower())
    direction = str(direction).strip().upper()
    config = data["stocks"].get(ticker)
    if not config:
        print(f"Ticker {ticker} not found.")
        return
    before = list(config.get("valuation_targets", []))
    config["valuation_targets"] = [x for x in before if not (
        x.get("metric") == metric and float(x.get("target", -1)) == float(threshold)
        and x.get("direction", "TRIM").upper() == direction)]
    if len(config["valuation_targets"]) == len(before):
        print("Valuation target not found.")
        return
    if not config.get("targets") and not config["valuation_targets"]:
        del data["stocks"][ticker]
    save_watchlist(data)
    print(f"Removed {direction} valuation target for {ticker}.")


def remove_target(ticker, target):
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    if ticker not in data["stocks"]:
        print(f"Ticker {ticker} not found in watchlist.")
        return

    targets = data["stocks"][ticker]["targets"]
    if target not in targets:
        print(f"Target {target} not found for {ticker}.")
        return

    targets.remove(target)
    if targets:
        data["stocks"][ticker]["targets"] = sorted(targets)
    else:
        del data["stocks"][ticker]
    save_watchlist(data)
    print(f"Removed target {target} for {ticker}.")


def remove_all(ticker):
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    removed = ticker in data["stocks"] or ticker in data["research"]
    data["stocks"].pop(ticker, None)
    data["research"].pop(ticker, None)
    if not removed:
        print(f"Ticker {ticker} not found.")
        return
    save_watchlist(data)
    print(f"Removed {ticker} from watchlist/research.")


def set_group(ticker, group):
    """Optional manual override. Automatic classification remains the default."""
    ticker = normalize_ticker(ticker)
    group = group.strip() or "Uncategorized"
    overrides = _load_json(OVERRIDES_FILE, {})
    overrides[ticker] = group
    _save_json(OVERRIDES_FILE, overrides)
    print(f"Manual group override saved for {ticker}: {group}")


def add_research(ticker, notes=""):
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    data["research"][ticker] = {"notes": notes.strip()}
    data["stocks"].pop(ticker, None)
    save_watchlist(data)
    print(f"Added {ticker} to research list.")
    print(f"Automatic group: {get_group(ticker)}")


def remove_research(ticker):
    data = load_watchlist()
    ticker = normalize_ticker(ticker)
    if ticker not in data["research"]:
        print(f"{ticker} is not in the research list.")
        return
    del data["research"][ticker]
    save_watchlist(data)
    print(f"Removed {ticker} from research list.")


def get_current_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        price = getattr(fast_info, "last_price", None) or getattr(fast_info, "lastPrice", None)
        if price is not None and isinstance(price, (int, float)) and price > 0:
            return round(float(price), 2)
    except Exception as e:
        print(f"Could not fetch price for {ticker}: {e}")
    return None


def get_valuation(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        result = {}
        for key, label in (("trailingPE", "P/E"), ("forwardPE", "Forward P/E"), ("priceToSalesTrailing12Months", "P/S")):
            value = info.get(key)
            result[label] = float(value) if isinstance(value, (int, float)) and value > 0 else None
        return result
    except Exception as e:
        print(f"Could not fetch valuation for {ticker}: {e}")
        return {"P/E": None, "Forward P/E": None, "P/S": None}


def classify_targets(targets, current_price):
    targets = sorted(float(t) for t in targets)
    if current_price is None:
        return targets, [], []
    add_targets = [t for t in targets if t < current_price]
    trim_targets = [t for t in targets if t > current_price]
    at_price = [t for t in targets if t == current_price]
    return add_targets, trim_targets, at_price


def price_delta(target, current):
    if current is None or current == 0:
        return ""
    return f"{((target / current) - 1.0) * 100.0:+.1f}%"


def format_target_line(targets, current_price, label):
    if not targets:
        return None
    parts = []
    for target in targets:
        delta = price_delta(target, current_price)
        parts.append(f"${target:,.2f} ({delta})" if delta else f"${target:,.2f}")
    return f"{label}: " + " → ".join(parts)


def group_sort_key(group):
    try:
        return (GROUP_ORDER.index(group), group.lower())
    except ValueError:
        return (len(GROUP_ORDER), group.lower())


def build_group_blocks(data):
    groups = {}

    for ticker, config in data["stocks"].items():
        group = get_group(ticker)
        current = get_current_price(ticker)
        add_targets, trim_targets, at_price = classify_targets(config.get("targets", []), current)
        lines = [f"**{ticker}** — {f'${current:,.2f}' if current is not None else 'N/A'}"]
        vals = get_valuation(ticker)
        val_line = " | ".join(f"{label}: {value:.1f}×" if value is not None else f"{label}: N/A" for label, value in vals.items())
        lines.append(f"📊 {val_line}")
        valuation_targets = config.get("valuation_targets", [])
        for vt in valuation_targets:
            metric_labels = {"pe": "P/E", "forward_pe": "Forward P/E", "ps": "P/S"}
            metric = str(vt.get("metric", "")).lower()
            direction = str(vt.get("direction", "TRIM")).upper()
            threshold = float(vt.get("target", 0))
            if metric in metric_labels:
                symbol = "🟢" if direction == "ADD" else "🔴"
                op = "≤" if direction == "ADD" else "≥"
                lines.append(f"{symbol} {direction} WATCH: {metric_labels[metric]} {op} {threshold:.1f}×")
        add_line = format_target_line(add_targets, current, "🟢 ADD")
        trim_line = format_target_line(trim_targets, current, "🔴 TRIM")
        at_line = format_target_line(at_price, current, "🟡 AT PRICE")
        if add_line:
            lines.append(add_line)
        if trim_line:
            lines.append(trim_line)
        if at_line:
            lines.append(at_line)
        if not add_line and not trim_line and not at_line:
            lines.append("No active target")
        groups.setdefault(group, []).append("\n".join(lines))

    for ticker, config in data["research"].items():
        group = get_group(ticker)
        notes = config.get("notes", "")
        block = [f"**{ticker}**", "🔎 Research needed — no target"]
        if notes:
            block.append(notes)
        groups.setdefault(f"🔎 Research — {group}", []).append("\n".join(block))

    for group in groups:
        groups[group].sort(key=lambda block: block.split("**")[1].split("**")[0].upper())

    return dict(sorted(groups.items(), key=lambda item: group_sort_key(item[0].replace("🔎 Research — ", ""))))


def embed_size(embed):
    return len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed.get("footer", {}).get("text", ""))


def post_embeds(embeds):
    if not DISCORD_WEBHOOK_URL:
        print("Error: No Discord webhook URL configured.")
        return

    chunks, current, current_size = [], [], 0
    for embed in embeds:
        size = embed_size(embed)
        if current and (len(current) >= 10 or current_size + size > 5800):
            chunks.append(current)
            current, current_size = [], 0
        current.append(embed)
        current_size += size
    if current:
        chunks.append(current)

    for chunk in chunks:
        try:
            resp = requests.post(
                DISCORD_WEBHOOK_URL,
                json={"username": "Watchlist Bot", "embeds": chunk},
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"Failed to send watchlist to Discord: {e}")
            return
    print(f"Watchlist sent to Discord in {len(chunks)} message(s).")


def send_watchlist_to_discord():
    data = load_watchlist()
    if not data["stocks"] and not data["research"]:
        print("Watchlist and research list are empty – nothing to send.")
        return

    groups = build_group_blocks(data)
    total_items = len(data["stocks"]) + len(data["research"])
    embeds = [{
        "title": "📋 INVESTMENT WATCHLIST",
        "description": (
            "**Current prices** are live from Yahoo Finance.\n"
            "**Groups** are automatically classified from company/industry information.\n"
            "🟢 **ADD** = target below current price\n"
            "🔴 **TRIM** = target above current price\n"
            "Targets are always shown from **low → high**.\n"
            "Valuation shows trailing P/E, forward P/E and P/S. Valuation alerts use your selected multiple threshold."
        ),
        "color": 3447003,
        "footer": {"text": f"{total_items} companies monitored"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]

    for group, blocks in groups.items():
        description = "\n\n".join(blocks)
        if len(description) <= 3800:
            embeds.append({"title": group, "description": description, "color": 3447003})
            continue
        current, current_len, part = [], 0, 1
        for block in blocks:
            extra = len(block) + (2 if current else 0)
            if current and current_len + extra > 3800:
                embeds.append({"title": f"{group} ({part})", "description": "\n\n".join(current), "color": 3447003})
                current, current_len, part = [], 0, part + 1
            current.append(block)
            current_len += extra
        if current:
            embeds.append({"title": f"{group} ({part})" if part > 1 else group, "description": "\n\n".join(current), "color": 3447003})

    post_embeds(embeds)


def list_watchlist():
    data = load_watchlist()
    if not data["stocks"] and not data["research"]:
        print("Watchlist is empty.")
        return

    print("\nACTIVE WATCHLIST")
    print("=" * 70)
    for group in sorted({get_group(t) for t in data["stocks"]}, key=group_sort_key):
        print(f"\n[{group}]")
        for ticker, config in sorted(data["stocks"].items()):
            if get_group(ticker) == group:
                targets = ", ".join(f"${t:.2f}" for t in sorted(config.get("targets", [])))
                print(f"{ticker}: {targets}")
                for vt in config.get("valuation_targets", []):
                    print(f"  {vt.get('direction', 'TRIM')} {vt.get('metric')} {vt.get('target')}x")

    if data["research"]:
        print("\nRESEARCH NEEDED")
        print("=" * 70)
        for ticker, config in sorted(data["research"].items()):
            notes = f" — {config['notes']}" if config.get("notes") else ""
            print(f"{ticker} [{get_group(ticker)}]{notes}")


def usage():
    print("""Usage:
  python watchlist_manager.py ADD TICKER TARGET
  python watchlist_manager.py REMOVE TICKER TARGET
  python watchlist_manager.py VALUATION_ADD TICKER METRIC THRESHOLD [ADD|TRIM]
  python watchlist_manager.py VALUATION_REMOVE TICKER METRIC THRESHOLD [ADD|TRIM]
  python watchlist_manager.py REMOVE_ALL TICKER
  python watchlist_manager.py SET_GROUP TICKER GROUP...   # optional manual override
  python watchlist_manager.py RESEARCH_ADD TICKER [NOTES...]
  python watchlist_manager.py RESEARCH_REMOVE TICKER
  python watchlist_manager.py LIST
  python watchlist_manager.py STATUS

Examples:
  python watchlist_manager.py ADD AMD 260
  python watchlist_manager.py VALUATION_ADD MA forward_pe 35 TRIM
  python watchlist_manager.py SET_GROUP NVDA "Semiconductors & Hardware"
  python watchlist_manager.py RESEARCH_ADD AVGO "Need valuation research"
  python watchlist_manager.py STATUS
""")


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    action = sys.argv[1].upper()
    if action == "ADD":
        if len(sys.argv) < 4:
            print("ADD requires TICKER and TARGET.")
            sys.exit(1)
        add_target(sys.argv[2], float(sys.argv[3]))
    elif action == "REMOVE":
        if len(sys.argv) < 4:
            print("REMOVE requires TICKER and TARGET.")
            sys.exit(1)
        remove_target(sys.argv[2], float(sys.argv[3]))
    elif action == "VALUATION_ADD":
        if len(sys.argv) < 5:
            print("VALUATION_ADD requires TICKER METRIC THRESHOLD [ADD|TRIM].")
            sys.exit(1)
        add_valuation_target(sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else "TRIM")
    elif action == "VALUATION_REMOVE":
        if len(sys.argv) < 5:
            print("VALUATION_REMOVE requires TICKER METRIC THRESHOLD [ADD|TRIM].")
            sys.exit(1)
        remove_valuation_target(sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else "TRIM")
    elif action == "REMOVE_ALL":
        if len(sys.argv) < 3:
            print("REMOVE_ALL requires TICKER.")
            sys.exit(1)
        remove_all(sys.argv[2])
    elif action == "SET_GROUP":
        if len(sys.argv) < 4:
            print("SET_GROUP requires TICKER and GROUP.")
            sys.exit(1)
        set_group(sys.argv[2], " ".join(sys.argv[3:]))
    elif action == "RESEARCH_ADD":
        if len(sys.argv) < 3:
            print("RESEARCH_ADD requires TICKER.")
            sys.exit(1)
        add_research(sys.argv[2], " ".join(sys.argv[3:]))
    elif action == "RESEARCH_REMOVE":
        if len(sys.argv) < 3:
            print("RESEARCH_REMOVE requires TICKER.")
            sys.exit(1)
        remove_research(sys.argv[2])
    elif action == "LIST":
        list_watchlist()
    elif action in {"STATUS", "SEND"}:
        send_watchlist_to_discord()
    else:
        print(f"Unknown action: {action}")
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
