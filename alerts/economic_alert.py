import os
import json
import requests
from datetime import datetime

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_ECONOMIC_WEBHOOK") or os.environ.get("DISCORD_SENTIMENT_WEBHOOK")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
TE_API_KEY = os.environ.get("TRADING_ECONOMICS_API_KEY")  # optional
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "economic_state.json")

# FRED series IDs and human-readable names
SERIES = {
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (All Urban Consumers)",
    "A191RL1Q225SBEA": "GDP Growth Rate (QoQ Annualized)",
    "PCEPI": "Core PCE Price Index",
    "PAYEMS": "Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims (Weekly)",
}

# Mapping from FRED series ID to Trading Economics indicator code
# You can find the correct codes at https://tradingeconomics.com/api/indicators
TE_MAP = {
    "UNRATE": "unemployment rate",
    "CPIAUCSL": "inflation cpi",
    "A191RL1Q225SBEA": "gdp growth rate",
    "PCEPI": "pce price index",
    "PAYEMS": "nonfarm payrolls",
    "ICSA": "initial jobless claims",
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

def fetch_fred_data(series_id, limit=2):
    """Fetch latest observations from FRED."""
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

def fetch_te_forecast(series_id):
    """Fetch forecast (consensus) from Trading Economics."""
    if not TE_API_KEY:
        return None
    indicator = TE_MAP.get(series_id)
    if not indicator:
        return None
    url = f"https://api.tradingeconomics.com/indicators/forecast?c={TE_API_KEY}&d1={indicator}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and len(data) > 0:
            return data[0].get("Forecast")
    except Exception as e:
        print(f"Could not fetch forecast for {series_id}: {e}")
    return None

def format_value(value, series_name):
    """Format a number based on the series type."""
    if value is None:
        return "N/A"
    if "Rate" in series_name or "Unemployment" in series_name or "Growth" in series_name:
        return f"{value:.2f}%"
    elif "Claims" in series_name or "Payrolls" in series_name:
        return f"{value:,.0f}"
    else:
        return f"{value:,.2f}"

def format_change(current, previous):
    if previous is None:
        return "N/A"
    diff = current - previous
    arrow = "🟢" if diff > 0 else "🔴" if diff < 0 else "⚪"
    return f"{arrow} {diff:+.2f}"

def send_discord_alert(series_name, date, current, previous, forecast):
    if not WEBHOOK_URL:
        print("Error: Discord webhook not configured.")
        return

    # Format all values
    current_str = format_value(current, series_name)
    prev_str = format_value(previous, series_name) if previous is not None else "N/A"
    forecast_str = format_value(forecast, series_name) if forecast is not None else "N/A"

    # Determine if actual beat forecast
    beat_forecast = ""
    if forecast is not None and previous is not None:
        diff_vs_forecast = current - forecast
        if abs(diff_vs_forecast) < 0.01:
            beat_forecast = "✅ In line with expectations"
        elif diff_vs_forecast > 0:
            beat_forecast = "🔥 Hot (above forecast)"
        else:
            beat_forecast = "❄️ Soft (below forecast)"

    # Additional note for GDP
    note = ""
    if "GDP" in series_name:
        note = "\n*(QoQ annualized)*"

    # Build fields
    fields = [
        {"name": "Current", "value": current_str, "inline": True},
        {"name": "Previous", "value": prev_str, "inline": True},
        {"name": "Expected", "value": forecast_str, "inline": True},
        {"name": "Change (vs Prev)", "value": format_change(current, previous) if previous is not None else "N/A", "inline": True},
    ]
    if beat_forecast:
        fields.append({"name": "Assessment", "value": beat_forecast, "inline": False})

    payload = {
        "username": "Sentiment Man",
        "embeds": [
            {
                "title": f"📊 {series_name}",
                "description": f"**Latest Release:** {date}{note}",
                "color": 3447003,
                "fields": fields,
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

    if not TE_API_KEY:
        print("Warning: TRADING_ECONOMICS_API_KEY not set – expected values will be skipped.")

    state = load_state()
    new_alerts = []

    for series_id, name in SERIES.items():
        observations = fetch_fred_data(series_id, limit=2)
        if len(observations) == 0:
            print(f"Warning: No data for {name} ({series_id})")
            continue

        latest_date, latest_value = observations[0]
        previous_value = observations[1][1] if len(observations) > 1 else None

        # Fetch forecast if available
        forecast = fetch_te_forecast(series_id) if TE_API_KEY else None

        # Check if this is a new release
        last_entry = state.get(series_id, {})
        last_date = last_entry.get("date")
        last_value = last_entry.get("value")

        if last_date is None or latest_date > last_date or (latest_date == last_date and latest_value != last_value):
            print(f"New data for {name}: {latest_date} = {latest_value} (prev: {previous_value}, forecast: {forecast})")
            send_discord_alert(name, latest_date, latest_value, previous_value, forecast)
            state[series_id] = {"date": latest_date, "value": latest_value}
            new_alerts.append(f"{name} -> {latest_value} ({latest_date})")
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
