import os
import json
import requests
from datetime import datetime

# ------------------------------------------------------------
# Configuration (unchanged)
# ------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_ECONOMIC_WEBHOOK") or os.environ.get("DISCORD_SENTIMENT_WEBHOOK")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "economic_state.json")

SERIES = {
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (All Urban Consumers)",
    "A191RL1Q225SBEA": "GDP Growth Rate (QoQ Annualized)",
    "PCEPI": "Core PCE Price Index",
    "PAYEMS": "Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims (Weekly)",
    "DFEDTARU": "Fed Funds Target Rate (Upper)",
    "DFEDTARL": "Fed Funds Target Rate (Lower)",
}

# ------------------------------------------------------------
# Helpers (unchanged)
# ------------------------------------------------------------

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def fetch_fred_data(series_id, limit=2):
    if not FRED_API_KEY:
        print("Error: FRED_API_KEY is missing.")
        return []
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&api_key={FRED_API_KEY}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit={limit}"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])
        result = []
        for obs in observations:
            value_str = obs.get("value")
            if value_str is None or value_str == ".":
                continue
            result.append((obs.get("date"), float(value_str)))
        return result
    except Exception as e:
        print(f"Error fetching {series_id}: {e}")
        return []

def should_show_percent(series_name):
    keywords = ["Rate", "Unemployment", "Growth"]
    return any(kw in series_name for kw in keywords)

def format_change(current, previous):
    if previous is None:
        return "N/A"
    diff = current - previous
    arrow = "🟢" if diff > 0 else "🔴" if diff < 0 else "⚪"
    return f"{arrow} {diff:+.2f}"

# ------------------------------------------------------------
# NEW: Batch Discord sender
# ------------------------------------------------------------

def send_batch_discord_alert(alerts):
    """
    alerts: list of dicts with keys:
        - name
        - date
        - current
        - previous
        - note (optional)
    """
    if not WEBHOOK_URL:
        print("Error: Discord webhook not configured.")
        return

    # Build fields
    fields = []
    for alert in alerts:
        name = alert["name"]
        date = alert["date"]
        current = alert["current"]
        previous = alert["previous"]
        note = alert.get("note", "")

        is_percent = should_show_percent(name)
        if is_percent:
            current_str = f"{current:.2f}%"
            prev_str = f"{previous:.2f}%" if previous is not None else "N/A"
            change_str = format_change(current, previous) if previous is not None else "N/A"
        elif "Claims" in name or "Payrolls" in name:
            current_str = f"{current:,.0f}"
            prev_str = f"{previous:,.0f}" if previous is not None else "N/A"
            change_str = format_change(current, previous) if previous is not None else "N/A"
        else:
            current_str = f"{current:,.2f}"
            prev_str = f"{previous:,.2f}" if previous is not None else "N/A"
            change_str = format_change(current, previous) if previous is not None else "N/A"

        field_value = (
            f"**Current:** {current_str}\n"
            f"**Previous:** {prev_str}\n"
            f"**Change:** {change_str}"
        )
        if note:
            field_value += f"\n*{note}*"

        fields.append({
            "name": f"📊 {name} – {date}",
            "value": field_value,
            "inline": False
        })

    payload = {
        "username": "Sentiment Man",
        "embeds": [
            {
                "title": "📊 Economic Data Updates",
                "color": 3447003,
                "fields": fields,
                "footer": {"text": "FRED (Federal Reserve)"},
                "timestamp": datetime.utcnow().isoformat()
            }
        ]
    }

    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print(f"Batch alert sent for {len(alerts)} indicators.")
    except Exception as e:
        print(f"Failed to send Discord batch alert: {e}")

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    if not FRED_API_KEY:
        print("Error: FRED_API_KEY environment variable not set. Exiting.")
        return

    state = load_state()
    new_alerts_data = []      # store alert details for batching
    new_series_updated = []   # just for logging

    for series_id, name in SERIES.items():
        observations = fetch_fred_data(series_id, limit=2)
        if len(observations) == 0:
            print(f"Warning: No data for {name} ({series_id})")
            continue

        latest_date, latest_value = observations[0]
        previous_value = observations[1][1] if len(observations) > 1 else None

        last_entry = state.get(series_id, {})
        last_date = last_entry.get("date")
        last_value = last_entry.get("value")

        if last_date is None or latest_date > last_date or (latest_date == last_date and latest_value != last_value):
            print(f"New data for {name}: {latest_date} = {latest_value} (prev: {previous_value})")
            # Prepare alert data
            note = ""
            if "GDP" in name:
                note = "Quarter-over-quarter, annualized"
            elif "Fed Funds" in name:
                note = "Federal Reserve target range"

            new_alerts_data.append({
                "name": name,
                "date": latest_date,
                "current": latest_value,
                "previous": previous_value,
                "note": note,
            })
            new_series_updated.append(f"{name} -> {latest_value} ({latest_date})")
            state[series_id] = {"date": latest_date, "value": latest_value}
        else:
            print(f"No new data for {name} (last: {last_date})")

    # Send a single batch alert if there are any updates
    if new_alerts_data:
        send_batch_discord_alert(new_alerts_data)
        save_state(state)
        print(f"✅ Updated state file with {len(new_alerts_data)} new indicators.")
    else:
        print("ℹ️ No new economic data released since last check.")

if __name__ == "__main__":
    print("Checking US economic data...")
    main()
