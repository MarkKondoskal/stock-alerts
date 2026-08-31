import os
import json
import requests
from datetime import datetime

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

# Use DISCORD_ECONOMIC_WEBHOOK if set; otherwise fall back to sentiment webhook
WEBHOOK_URL = os.environ.get("DISCORD_ECONOMIC_WEBHOOK") or os.environ.get("DISCORD_SENTIMENT_WEBHOOK")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "economic_state.json")

# FRED series IDs and human-readable names
SERIES = {
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (All Urban Consumers)",
    "GDP": "Gross Domestic Product (GDP)",
    "PCEPI": "Core PCE (Inflation)",
    "PAYEMS": "Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims (Weekly)",
}

# ------------------------------------------------------------
# Helpers
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

def fetch_fred_data(series_id):
    """
    Fetch the latest observation for a given FRED series.
    Returns (date, value) or (None, None) if error.
    """
    if not FRED_API_KEY:
        print("Error: FRED_API_KEY is missing.")
        return None, None

    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&api_key={FRED_API_KEY}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit=1"
    )

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        observations = data.get("observations", [])
        if not observations:
            return None, None

        obs = observations[0]
        value_str = obs.get("value")
        if value_str is None or value_str == ".":
            return None, None

        date = obs.get("date")
        value = float(value_str)

        return date, value

    except Exception as e:
        print(f"Error fetching {series_id}: {e}")
        return None, None

def send_discord_alert(series_name, date, value):
    """Send a formatted embed to Discord."""
    if not WEBHOOK_URL:
        print("Error: Discord webhook not configured.")
        return

    # Format based on series type
    if "Rate" in series_name or "Unemployment" in series_name:
        display_value = f"{value:.2f}%"
    elif "Claims" in series_name:
        display_value = f"{value:,.0f}"
    else:
        display_value = f"{value:,.2f}"

    payload = {
        "username": "Sentiment Man",
        "embeds": [
            {
                "title": f"📊 {series_name}",
                "description": f"**Latest Release:** {date}",
                "color": 3447003,  # Blue
                "fields": [
                    {
                        "name": "Value",
                        "value": display_value,
                        "inline": True
                    },
                    {
                        "name": "Data Source",
                        "value": "FRED (Federal Reserve)",
                        "inline": True
                    }
                ],
                "footer": {"text": "Economic Data Monitor"},
                "timestamp": datetime.utcnow().isoformat()
            }
        ]
    }

    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print(f"Alert sent for {series_name}")
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    if not FRED_API_KEY:
        print("Error: FRED_API_KEY environment variable not set. Exiting.")
        return

    state = load_state()
    new_alerts = []

    for series_id, name in SERIES.items():
        date, value = fetch_fred_data(series_id)
        if date is None or value is None:
            print(f"Warning: No data for {name} ({series_id})")
            continue

        # Check if we already have this data point
        last_entry = state.get(series_id, {})
        last_date = last_entry.get("date")
        last_value = last_entry.get("value")

        # If date is newer, or date is same but value changed (revision), send alert
        if last_date is None or date > last_date or (date == last_date and value != last_value):
            print(f"New data for {name}: {date} = {value}")
            send_discord_alert(name, date, value)
            state[series_id] = {"date": date, "value": value}
            new_alerts.append(f"{name} -> {value} ({date})")
        else:
            print(f"No new data for {name} (last: {last_date})")

    if new_alerts:
        save_state(state)
        print(f"✅ Updated state file with {len(new_alerts)} new indicators.")
    else:
        print("ℹ️ No new economic data released since last check.")

if __name__ == "__main__":
    print("Checking US economic data...")
    main()
