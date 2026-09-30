import json
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

GROUP_ORDER = [
    "Semiconductors & Hardware",
    "Software & Internet",
    "Cloud & Data Centers",
    "Space",
    "Energy & Power",
    "Industrials",
    "Consumer & Internet",
    "Telecom",
    "Healthcare",
    "Uncategorized",
]


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
        # Convert the old flat format automatically.
        stocks = {}
        research = {}
        for ticker, targets in (raw or {}).items():
            ticker = str(ticker).strip().upper()
            if ticker:
                stocks[ticker] = {
                    "group": "Uncategorized",
                    "targets": sorted({float(t) for t in targets}),
                }

    normalized_stocks = {}
    for ticker, config in stocks.items():
        ticker = str(ticker).strip().upper()
        if not ticker:
            continue
        if isinstance(config, dict):
            group = str(config.get("group", "Uncategorized")).strip() or "Uncategorized"
            targets = config.get("targets", []) or []
        else:
            group = "Uncategorized"
            targets = config or []
        normalized_stocks[ticker] = {
            "group": group,
            "targets": sorted({float(t) for t in targets}),
        }

    normalized_research = {}
    for ticker, config in research.items():
        ticker = str(ticker).strip().upper()
        if not ticker:
            continue
        config = config if isinstance(config, dict) else {}
        normalized_research[ticker] = {
            "group": str(config.get("group", "Uncategorized")).strip() or "Uncategorized",
            "notes": str(config.get("notes", "")).strip(),
        }

    return {"stocks": normalized_stocks, "research": normalized_research}


def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Watchlist saved.")


def add_target(ticker, target, group=None):
    data = load_watchlist()
    ticker = ticker.strip().upper()

    config = data["stocks"].get(
        ticker,
        {"group": group or "Uncategorized", "targets": []},
    )

    if group:
        config["group"] = group

    if target in config["targets"]:
        print(f"Target {target} already exists for {ticker}.")
        return

    config["targets"].append(target)
    config["targets"].sort()
    data["stocks"][ticker] = config

    # A target turns a research-only name back into an active watchlist stock.
    data["research"].pop(ticker, None)

    save_watchlist(data)
    print(f"Added target {target} for {ticker}.")


def remove_target(ticker, target):
    data = load_watchlist()
    ticker = ticker.strip().upper()

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
    ticker = ticker.strip().upper()

    removed = False
    if ticker in data["stocks"]:
        del data["stocks"][ticker]
        removed = True
    if ticker in data["research"]:
        del data["research"][ticker]
        removed = True

    if not removed:
        print(f"Ticker {ticker} not found.")
        return

    save_watchlist(data)
    print(f"Removed {ticker} from watchlist/research.")


def set_group(ticker, group):
    data = load_watchlist()
    ticker = ticker.strip().upper()
    group = group.strip() or "Uncategorized"

    if ticker in data["stocks"]:
        data["stocks"][ticker]["group"] = group
    elif ticker in data["research"]:
        data["research"][ticker]["group"] = group
    else:
        print(f"Ticker {ticker} not found. Add it first or use RESEARCH_ADD.")
        return

    save_watchlist(data)
    print(f"Set group for {ticker}: {group}")


def add_research(ticker, group="Uncategorized", notes=""):
    data = load_watchlist()
    ticker = ticker.strip().upper()

    data["research"][ticker] = {
        "group": group.strip() or "Uncategorized",
        "notes": notes.strip(),
    }

    # A research-only stock should not also be an active target list.
    data["stocks"].pop(ticker, None)

    save_watchlist(data)
    print(f"Added {ticker} to research list.")


def remove_research(ticker):
    data = load_watchlist()
    ticker = ticker.strip().upper()

    if ticker not in data["research"]:
        print(f"{ticker} is not in the research list.")
        return

    del data["research"][ticker]
    save_watchlist(data)
    print(f"Removed {ticker} from research list.")


def get_current_price(ticker):
    """Fetch live price for a ticker using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        price = getattr(fast_info, "last_price", None) or getattr(fast_info, "lastPrice", None)
        if price is not None and isinstance(price, (int, float)) and price > 0:
            return round(float(price), 2)
    except Exception as e:
        print(f"Could not fetch price for {ticker}: {e}")
    return None


def classify_targets(targets, current_price):
    targets = sorted(float(t) for t in targets)
    if current_price is None:
        return targets, []

    add_targets = [t for t in targets if t < current_price]
    trim_targets = [t for t in targets if t > current_price]
    at_price = [t for t in targets if t == current_price]
    return add_targets, trim_targets, at_price


def price_delta(target, current):
    if current is None or current == 0:
        return ""
    pct = ((target / current) - 1.0) * 100.0
    return f"{pct:+.1f}%"


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
    """Return compact Discord-ready text grouped by sector/category."""
    groups = {}

    # Active target stocks.
    for ticker, config in data["stocks"].items():
        group = config.get("group", "Uncategorized")
        current = get_current_price(ticker)
        add_targets, trim_targets, at_price = classify_targets(config.get("targets", []), current)

        lines = [f"**{ticker}** — {f'${current:,.2f}' if current is not None else 'N/A'}"]
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

    # Research-only stocks.
    for ticker, config in data["research"].items():
        group = config.get("group", "Uncategorized")
        notes = config.get("notes", "")
        block = [f"**{ticker}**", "🔎 Research needed — no target"]
        if notes:
            block.append(notes)
        groups.setdefault(f"🔎 Research — {group}", []).append("\n".join(block))

    for group in groups:
        groups[group].sort(key=lambda block: block.split("**")[1].split("**")[0].upper())

    return dict(sorted(groups.items(), key=lambda item: group_sort_key(item[0].replace("🔎 Research — ", ""))))


def embed_size(embed):
    """Approximate the Discord embed character budget used by this message."""
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + len(embed.get("footer", {}).get("text", ""))
    )


def post_embeds(embeds):
    if not DISCORD_WEBHOOK_URL:
        print("Error: No Discord webhook URL configured.")
        return

    # Discord limits one message to 10 embeds and 6000 total embed characters.
    # Keep a little headroom so small metadata changes do not push us over the limit.
    chunks = []
    current = []
    current_size = 0

    for embed in embeds:
        size = embed_size(embed)
        if current and (len(current) >= 10 or current_size + size > 5800):
            chunks.append(current)
            current = []
            current_size = 0

        current.append(embed)
        current_size += size

    if current:
        chunks.append(current)

    for chunk in chunks:
        payload = {
            "username": "Watchlist Bot",
            "embeds": chunk,
        }
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=20)
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

    embeds = [
        {
            "title": "📋 INVESTMENT WATCHLIST",
            "description": (
                "**Current prices** are live from Yahoo Finance.\n"
                "🟢 **ADD** = target below current price\n"
                "🔴 **TRIM** = target above current price\n"
                "Targets are always shown from **low → high**."
            ),
            "color": 3447003,
            "footer": {"text": f"{total_items} companies monitored"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]

    for group, blocks in groups.items():
        description = "\n\n".join(blocks)

        # Keep each embed comfortably below Discord's 4096-character description limit.
        if len(description) <= 3800:
            embeds.append(
                {
                    "title": group,
                    "description": description,
                    "color": 3447003,
                }
            )
            continue

        current = []
        current_len = 0
        part = 1
        for block in blocks:
            extra = len(block) + (2 if current else 0)
            if current and current_len + extra > 3800:
                embeds.append(
                    {
                        "title": f"{group} ({part})",
                        "description": "\n\n".join(current),
                        "color": 3447003,
                    }
                )
                current = []
                current_len = 0
                part += 1
            current.append(block)
            current_len += extra

        if current:
            embeds.append(
                {
                    "title": f"{group} ({part})" if part > 1 else group,
                    "description": "\n\n".join(current),
                    "color": 3447003,
                }
            )

    post_embeds(embeds)


def list_watchlist():
    data = load_watchlist()
    if not data["stocks"] and not data["research"]:
        print("Watchlist is empty.")
        return

    print("\nACTIVE WATCHLIST")
    print("=" * 70)
    for group in sorted({c.get("group", "Uncategorized") for c in data["stocks"].values()}, key=group_sort_key):
        print(f"\n[{group}]")
        for ticker, config in sorted(data["stocks"].items()):
            if config.get("group", "Uncategorized") == group:
                targets = ", ".join(f"${t:.2f}" for t in sorted(config.get("targets", [])))
                print(f"{ticker}: {targets}")

    if data["research"]:
        print("\nRESEARCH NEEDED")
        print("=" * 70)
        for ticker, config in sorted(data["research"].items()):
            notes = f" — {config['notes']}" if config.get("notes") else ""
            print(f"{ticker} [{config.get('group', 'Uncategorized')}]{notes}")


def usage():
    print(
        """Usage:
  python watchlist_manager.py ADD TICKER TARGET [GROUP...]
  python watchlist_manager.py REMOVE TICKER TARGET
  python watchlist_manager.py REMOVE_ALL TICKER
  python watchlist_manager.py SET_GROUP TICKER GROUP...
  python watchlist_manager.py RESEARCH_ADD TICKER [GROUP] [NOTES...]
  python watchlist_manager.py RESEARCH_REMOVE TICKER
  python watchlist_manager.py LIST
  python watchlist_manager.py STATUS

Examples:
  python watchlist_manager.py ADD AMD 260 "Semiconductors & Hardware"
  python watchlist_manager.py SET_GROUP NVDA "Semiconductors & Hardware"
  python watchlist_manager.py RESEARCH_ADD AVGO "Semiconductors & Hardware" "Need valuation research"
  python watchlist_manager.py STATUS
"""
    )


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    action = sys.argv[1].upper()

    if action == "ADD":
        if len(sys.argv) < 4:
            print("ADD requires TICKER and TARGET.")
            sys.exit(1)
        ticker = sys.argv[2]
        target = float(sys.argv[3])
        group = " ".join(sys.argv[4:]).strip() if len(sys.argv) > 4 else None
        add_target(ticker, target, group)

    elif action == "REMOVE":
        if len(sys.argv) < 4:
            print("REMOVE requires TICKER and TARGET.")
            sys.exit(1)
        remove_target(sys.argv[2], float(sys.argv[3]))

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
        ticker = sys.argv[2]
        group = sys.argv[3] if len(sys.argv) > 3 else "Uncategorized"
        notes = " ".join(sys.argv[4:]) if len(sys.argv) > 4 else ""
        add_research(ticker, group, notes)

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
