import os
import json
import requests
from datetime import datetime, timezone

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_ECONOMIC_WEBHOOK") or os.environ.get("DISCORD_SENTIMENT_WEBHOOK")
FRED_API_KEY = os.environ.get("FRED_API_KEY")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "economic_state.json")

# FRED series monitored by the economic-data workflow.
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
# State handling
# ------------------------------------------------------------

def load_state():
    """Load the last FRED observation stored for each series."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            raise ValueError("State file must contain a JSON object")

        return state

    except FileNotFoundError:
        print(
            "ℹ️ No economic_state.json found. "
            "The next successful run will initialize it without sending alerts."
        )
        return {}

    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(f"⚠️ Could not load economic state: {e}. Starting with empty state.")
        return {}


def save_state(state):
    """Atomically save economic state so a partial write cannot corrupt the file."""
    tmp_file = STATE_FILE + ".tmp"

    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")

        os.replace(tmp_file, STATE_FILE)
        return True

    except OSError as e:
        print(f"❌ Error saving economic state: {e}")

        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass

        return False


# ------------------------------------------------------------
# FRED
# ------------------------------------------------------------

def fetch_fred_data(series_id, limit=2):
    """Return the newest usable FRED observations as (date, value)."""
    if not FRED_API_KEY:
        print("❌ FRED_API_KEY is missing.")
        return []

    url = "https://api.stlouisfed.org/fred/series/observations"

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        observations = data.get("observations", [])

        result = []

        for observation in observations:
            date = observation.get("date")
            value_str = observation.get("value")

            if not date or value_str in (None, "."):
                continue

            try:
                value = float(value_str)
            except (TypeError, ValueError):
                continue

            result.append((date, value))

        return result

    except (requests.RequestException, ValueError, TypeError) as e:
        print(f"❌ Error fetching {series_id}: {e}")
        return []


# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------

def should_show_percent(series_name):
    keywords = ["Rate", "Unemployment", "Growth"]
    return any(keyword in series_name for keyword in keywords)


def format_change(current, previous):
    if previous is None:
        return "N/A"

    difference = current - previous

    icon = (
        "🟢"
        if difference > 0
        else "🔴"
        if difference < 0
        else "⚪"
    )

    return f"{icon} {difference:+.2f}"


# ------------------------------------------------------------
# Discord
# ------------------------------------------------------------

def send_discord_alert(series_name, date, current, previous):
    """Send one Discord message for one changed economic series."""

    if not WEBHOOK_URL:
        print("❌ Discord economic webhook is not configured.")
        return False

    is_percent = should_show_percent(series_name)

    if is_percent:
        current_str = f"{current:.2f}%"
        previous_str = (
            f"{previous:.2f}%"
            if previous is not None
            else "N/A"
        )

    elif "Claims" in series_name or "Payrolls" in series_name:
        current_str = f"{current:,.0f}"
        previous_str = (
            f"{previous:,.0f}"
            if previous is not None
            else "N/A"
        )

    else:
        current_str = f"{current:,.2f}"
        previous_str = (
            f"{previous:,.2f}"
            if previous is not None
            else "N/A"
        )

    change_str = (
        format_change(current, previous)
        if previous is not None
        else "N/A"
    )

    note = ""

    if "GDP" in series_name:
        note = "\n*(Quarter-over-quarter, annualized)*"

    elif "Fed Funds" in series_name:
        note = "\n*(Federal Reserve target range)*"

    payload = {
        "username": "Economic Data Monitor",
        "embeds": [
            {
                "title": f"📊 {series_name}",
                "description": (
                    f"**Latest Release:** {date}"
                    f"{note}"
                ),
                "color": 3447003,
                "fields": [
                    {
                        "name": "Current",
                        "value": current_str,
                        "inline": True,
                    },
                    {
                        "name": "Previous",
                        "value": previous_str,
                        "inline": True,
                    },
                    {
                        "name": "Change",
                        "value": change_str,
                        "inline": True,
                    },
                    {
                        "name": "Data Source",
                        "value": "FRED (Federal Reserve)",
                        "inline": False,
                    },
                ],
                "footer": {
                    "text": "Economic Data Monitor"
                },
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        ],
    }

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        print(f"✅ Alert sent for {series_name}")
        return True

    except requests.RequestException as e:
        print(
            f"❌ Failed to send Discord alert "
            f"for {series_name}: {e}"
        )
        return False


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    if not FRED_API_KEY:
        print(
            "❌ FRED_API_KEY environment variable "
            "not set. Exiting."
        )
        return

    state = load_state()

    print(
        f"📂 Loaded state with "
        f"{len(state)} series entries."
    )

    state_changed = False

    alerts_sent = []
    initialized = []

    for series_id, name in SERIES.items():

        observations = fetch_fred_data(
            series_id,
            limit=2,
        )

        if not observations:
            print(
                f"⚠️ No data for {name} "
                f"({series_id}) – skipping"
            )
            continue

        latest_date, latest_value = observations[0]

        previous_value = (
            observations[1][1]
            if len(observations) > 1
            else None
        )

        last_entry = state.get(series_id)

        # ----------------------------------------------------
        # First observation for this series
        #
        # Establish a baseline.
        # DO NOT send an alert.
        # ----------------------------------------------------

        if (
            not isinstance(last_entry, dict)
            or last_entry.get("date") is None
        ):

            state[series_id] = {
                "date": latest_date,
                "value": latest_value,
            }

            state_changed = True
            initialized.append(name)

            print(
                f"🟦 {name}: initialized at "
                f"{latest_date} = {latest_value} "
                f"(no alert)"
            )

            continue

        last_date = last_entry.get("date")
        last_value = last_entry.get("value")

        # ----------------------------------------------------
        # Detect ONLY this series changing.
        # ----------------------------------------------------

        if latest_date > last_date:

            reason = (
                f"new release "
                f"({latest_date} > {last_date})"
            )

            changed = True

        elif (
            latest_date == last_date
            and latest_value != last_value
        ):

            reason = (
                f"revision "
                f"({last_value} → {latest_value})"
            )

            changed = True

        else:

            reason = "no change"
            changed = False

        print(
            f"🔍 {name}: {reason}"
        )

        if not changed:
            continue

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Only update state AFTER Discord successfully
        # receives the alert.
        #
        # If Discord fails, this indicator will be retried
        # during the next workflow run.
        # ----------------------------------------------------

        if send_discord_alert(
            name,
            latest_date,
            latest_value,
            previous_value,
        ):

            state[series_id] = {
                "date": latest_date,
                "value": latest_value,
            }

            state_changed = True
            alerts_sent.append(name)

        else:

            print(
                f"⚠️ State NOT updated for {name}; "
                f"it will be retried next run."
            )

    # --------------------------------------------------------
    # Persist state
    # --------------------------------------------------------

    if state_changed:

        if save_state(state):
            print(
                f"💾 Economic state saved: "
                f"{len(state)} series tracked."
            )

    else:

        print(
            "ℹ️ No economic state changes."
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print(
        "--- Economic monitor summary ---"
    )

    print(
        f"Initialized without alerts: "
        f"{len(initialized)}"
    )

    print(
        f"Alerts sent: "
        f"{len(alerts_sent)}"
    )

    if alerts_sent:

        print(
            "Changed series: "
            + ", ".join(alerts_sent)
        )

    else:

        print(
            "No new/revised economic data detected."
        )


if __name__ == "__main__":
    print("Checking US economic data...")
    main()
