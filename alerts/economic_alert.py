from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

STATE_FILE = BASE_DIR / "economic_state.json"

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

FRED_API_KEY = os.environ.get("FRED_API_KEY")

DISCORD_WEBHOOK = (
    os.environ.get("DISCORD_ECONOMIC_WEBHOOK")
    or os.environ.get("DISCORD_SENTIMENT_WEBHOOK")
)


# ============================================================
# FRED SERIES
# ============================================================

SERIES = {
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI (All Urban Consumers)",
    "A191RL1Q225SBEA": "GDP Growth Rate (QoQ Annualized)",
    "PCEPI": "PCE Price Index",
    "PAYEMS": "Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims (Weekly)",
}


# ============================================================
# FEDERAL RESERVE
#
# We check the Federal Reserve's own FOMC statement separately.
#
# This is important because FRED can lag the actual FOMC
# announcement.
# ============================================================

FED_MONETARY_POLICY_URL = (
    "https://www.federalreserve.gov/monetarypolicy.htm"
)


# ============================================================
# STATE FUNCTIONS
# ============================================================

def load_state() -> dict:
    """
    Load persisted economic state.

    If the state file does not exist or is invalid,
    start with an empty state.
    """

    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception as exc:
        print(f"⚠️ Could not read economic state: {exc}")

    return {}


def save_state(state: dict) -> None:
    """
    Save economic state to disk.
    """

    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            indent=4,
            sort_keys=True,
        )


# ============================================================
# DISCORD
# ============================================================

def send_discord_alert(
    title: str,
    description: str,
    color: int = 0x3498DB,
) -> bool:
    """
    Send one alert to Discord.

    Returns:
        True  -> Discord accepted the message
        False -> message failed
    """

    if not DISCORD_WEBHOOK:
        print("❌ No Discord webhook configured.")
        return False

    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
            }
        ]
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK,
            json=payload,
            timeout=20,
        )

        if 200 <= response.status_code < 300:
            print("✅ Discord alert sent.")
            return True

        print(
            f"❌ Discord returned "
            f"{response.status_code}: "
            f"{response.text}"
        )

    except Exception as exc:
        print(f"❌ Discord request failed: {exc}")

    return False


# ============================================================
# FRED
# ============================================================

def fetch_fred_series(series_id: str) -> dict | None:
    """
    Fetch the latest usable observation from FRED.

    We deliberately only use the latest observation here.

    The previous value comes from our own state file rather
    than from FRED's second observation.

    This is important because the second FRED observation is
    NOT necessarily the value that our bot saw on its previous
    run.
    """

    if not FRED_API_KEY:
        print("❌ FRED_API_KEY is missing.")
        return None

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 10,
    }

    try:
        response = requests.get(
            FRED_API_URL,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

    except Exception as exc:
        print(
            f"❌ Failed to fetch FRED "
            f"{series_id}: {exc}"
        )
        return None

    observations = data.get("observations", [])

    for observation in observations:

        value_raw = observation.get("value")

        if value_raw in (None, "", "."):
            continue

        try:
            value = float(value_raw)
        except ValueError:
            continue

        return {
            "date": observation.get("date"),
            "value": value,
        }

    print(
        f"⚠️ No usable observation found "
        f"for {series_id}"
    )

    return None


# ============================================================
# FORMAT FRED VALUES
# ============================================================

def format_fred_value(series_id: str, value: float) -> str:
    """
    Format values for Discord.

    Percentage-based series are displayed with %.
    """

    percentage_series = {
        "UNRATE",
        "CPIAUCSL",
        "A191RL1Q225SBEA",
        "PCEPI",
    }

    if series_id in percentage_series:
        return f"{value:.2f}%"

    if series_id == "PAYEMS":
        return f"{value:,.0f}"

    if series_id == "ICSA":
        return f"{value:,.0f}"

    return f"{value:,.2f}"


# ============================================================
# CHECK FRED SERIES
# ============================================================

def check_fred_series(
    series_id: str,
    name: str,
    state: dict,
) -> None:

    latest = fetch_fred_series(series_id)

    if latest is None:
        return

    latest_date = latest["date"]
    latest_value = latest["value"]

    previous = state.get(series_id)

    # --------------------------------------------------------
    # FIRST RUN
    # --------------------------------------------------------

    if previous is None:

        state[series_id] = {
            "date": latest_date,
            "value": latest_value,
        }

        print(
            f"🟡 {name}: "
            f"initialised at "
            f"{format_fred_value(series_id, latest_value)} "
            f"({latest_date})"
        )

        return

    # --------------------------------------------------------
    # EXISTING STATE
    # --------------------------------------------------------

    last_date = previous.get("date")
    last_value = previous.get("value")

    try:
        last_value = float(last_value)
    except (TypeError, ValueError):
        last_value = None

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # A new DATE does NOT automatically mean a new DATA VALUE.
    #
    # We only alert if the actual value changed.
    # --------------------------------------------------------

    if last_value is None:

        changed = True
        reason = (
            f"previous value unavailable "
            f"→ {latest_value}"
        )

    elif latest_value != last_value:

        changed = True

        reason = (
            f"{format_fred_value(series_id, last_value)} "
            f"→ "
            f"{format_fred_value(series_id, latest_value)}"
        )

    else:

        changed = False

        if latest_date != last_date:
            reason = (
                f"new observation date "
                f"({latest_date}), "
                f"but value unchanged"
            )
        else:
            reason = "no change"

    print(
        f"🔍 {name}: {reason}"
    )

    # --------------------------------------------------------
    # NOTHING CHANGED
    #
    # But if FRED published a new date with the same value,
    # update the date silently.
    # --------------------------------------------------------

    if not changed:

        if latest_date != last_date:

            state[series_id] = {
                "date": latest_date,
                "value": latest_value,
            }

            print(
                f"   ↳ Date updated silently: "
                f"{last_date} → {latest_date}"
            )

        return

    # --------------------------------------------------------
    # VALUE CHANGED
    # --------------------------------------------------------

    previous_display = format_fred_value(
        series_id,
        last_value,
    )

    current_display = format_fred_value(
        series_id,
        latest_value,
    )

    if latest_value > last_value:
        color = 0x2ECC71
        direction = "increased"

    else:
        color = 0xE74C3C
        direction = "decreased"

    description = (
        f"**Current:** {current_display}\n"
        f"**Previous:** {previous_display}\n"
        f"**Change:** "
        f"{latest_value - last_value:+,.2f}\n"
        f"**Release:** {latest_date}\n\n"
        f"{name} {direction}."
    )

    # --------------------------------------------------------
    # ONLY UPDATE STATE AFTER DISCORD SUCCEEDS
    # --------------------------------------------------------

    sent = send_discord_alert(
        title=f"📊 Economic Data — {name}",
        description=description,
        color=color,
    )

    if sent:

        state[series_id] = {
            "date": latest_date,
            "value": latest_value,
        }

        print(
            f"💾 State updated for {series_id}"
        )

    else:

        print(
            f"⚠️ State NOT updated for {series_id} "
            f"because Discord failed."
        )


# ============================================================
# FEDERAL RESERVE FOMC
# ============================================================

def fetch_latest_fomc_statement() -> dict | None:
    """
    Find the latest FOMC statement directly from the
    Federal Reserve website.

    This avoids waiting for FRED to update its daily
    target-rate series.
    """

    try:

        response = requests.get(
            FED_MONETARY_POLICY_URL,
            timeout=20,
        )

        response.raise_for_status()

        html = response.text

    except Exception as exc:

        print(
            f"❌ Failed to fetch Federal Reserve "
            f"monetary policy page: {exc}"
        )

        return None

    # --------------------------------------------------------
    # Find the latest FOMC statement link.
    #
    # The Fed page contains a link such as:
    #
    # /newsevents/pressreleases/monetary20260916a.htm
    # --------------------------------------------------------

    matches = re.findall(
        r'href=["\']([^"\']*monetary\d{8}a\.htm)["\']',
        html,
        flags=re.IGNORECASE,
    )

    if not matches:
        print(
            "⚠️ Could not find an FOMC statement "
            "on the Federal Reserve website."
        )
        return None

    # Keep the latest unique URL.
    statement_path = matches[0]

    if statement_path.startswith("/"):
        statement_url = (
            "https://www.federalreserve.gov"
            + statement_path
        )
    else:
        statement_url = statement_path

    try:

        statement_response = requests.get(
            statement_url,
            timeout=20,
        )

        statement_response.raise_for_status()

        statement_html = statement_response.text

    except Exception as exc:

        print(
            f"❌ Failed to fetch FOMC statement: {exc}"
        )

        return None

    # --------------------------------------------------------
    # Extract the FOMC decision.
    #
    # Example:
    #
    # "raise the target range for the federal funds rate
    # by 1/4 percentage point to 3-3/4 to 4 percent"
    # --------------------------------------------------------

    pattern = (
        r"target range for the federal funds rate"
        r".{0,500}?"
        r"to\s+"
        r"([0-9]+(?:-[0-9]+)?(?:\s*[-–]\s*[0-9]+)?)"
        r"\s+to\s+"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*percent"
    )

    match = re.search(
        pattern,
        statement_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:

        # The HTML may contain encoded whitespace or tags,
        # so try a simpler version.
        text = re.sub(
            r"<[^>]+>",
            " ",
            statement_html,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    if not match:

        print(
            "⚠️ Could not extract the federal funds "
            "target range from the FOMC statement."
        )

        return None

    lower_raw = match.group(1)
    upper_raw = match.group(2)

    # --------------------------------------------------------
    # Convert things such as:
    #
    # 3-3/4
    #
    # into:
    #
    # 3.75
    # --------------------------------------------------------

    def parse_rate(value: str) -> float:

        value = value.strip()

        if "-" in value:

            parts = value.split("-")

            if len(parts) == 2:

                whole = float(parts[0])

                fraction = parts[1]

                if fraction == "1/4":
                    return whole + 0.25

                if fraction == "1/2":
                    return whole + 0.50

                if fraction == "3/4":
                    return whole + 0.75

        return float(value)

    lower = parse_rate(lower_raw)
    upper = parse_rate(upper_raw)

    # --------------------------------------------------------
    # Extract release date from URL.
    #
    # monetary20260916a.htm
    # -> 2026-09-16
    # --------------------------------------------------------

    date_match = re.search(
        r"monetary(\d{4})(\d{2})(\d{2})a\.htm",
        statement_url,
        flags=re.IGNORECASE,
    )

    if date_match:

        release_date = (
            f"{date_match.group(1)}-"
            f"{date_match.group(2)}-"
            f"{date_match.group(3)}"
        )

    else:

        release_date = None

    return {
        "date": release_date,
        "lower": lower,
        "upper": upper,
        "url": statement_url,
    }


# ============================================================
# CHECK FEDERAL RESERVE
# ============================================================

def check_federal_reserve(state: dict) -> None:
    """
    Check the latest FOMC target range directly from the Fed.

    This is separate from FRED because the official Fed
    announcement can occur before FRED updates its series.
    """

    latest = fetch_latest_fomc_statement()

    if latest is None:
        return

    latest_date = latest["date"]
    latest_lower = latest["lower"]
    latest_upper = latest["upper"]
    statement_url = latest["url"]

    previous = state.get("FED_FUNDS_TARGET_RANGE")

    # --------------------------------------------------------
    # FIRST RUN
    # --------------------------------------------------------

    if previous is None:

        state["FED_FUNDS_TARGET_RANGE"] = {
            "date": latest_date,
            "lower": latest_lower,
            "upper": latest_upper,
        }

        print(
            "🟡 Federal Reserve target range "
            f"initialised at "
            f"{latest_lower:.2f}%–{latest_upper:.2f}%"
        )

        return

    last_lower = float(
        previous.get("lower", latest_lower)
    )

    last_upper = float(
        previous.get("upper", latest_upper)
    )

    last_date = previous.get("date")

    # --------------------------------------------------------
    # ONLY THE RATE RANGE MATTERS.
    #
    # A new FOMC statement with the same target range
    # does NOT generate an alert.
    # --------------------------------------------------------

    lower_changed = latest_lower != last_lower
    upper_changed = latest_upper != last_upper

    if not lower_changed and not upper_changed:

        if latest_date != last_date:

            state["FED_FUNDS_TARGET_RANGE"] = {
                "date": latest_date,
                "lower": latest_lower,
                "upper": latest_upper,
            }

            print(
                "🔍 Federal Reserve target range: "
                "new statement, same rate — "
                "updated silently."
            )

        else:

            print(
                "🔍 Federal Reserve target range: "
                "no change"
            )

        return

    # --------------------------------------------------------
    # RATE CHANGED
    # --------------------------------------------------------

    changes = []

    if lower_changed:

        changes.append(
            f"Lower: {last_lower:.2f}% → "
            f"{latest_lower:.2f}%"
        )

    if upper_changed:

        changes.append(
            f"Upper: {last_upper:.2f}% → "
            f"{latest_upper:.2f}%"
        )

    description = (
        f"**New target range:** "
        f"{latest_lower:.2f}% – {latest_upper:.2f}%\n\n"
        f"**Previous target range:** "
        f"{last_lower:.2f}% – {last_upper:.2f}%\n\n"
        f"**Change:**\n"
        + "\n".join(changes)
        + f"\n\n**FOMC date:** {latest_date}\n"
        f"**Source:** Federal Reserve"
    )

    sent = send_discord_alert(
        title="🏦 Federal Reserve — FOMC Rate Decision",
        description=description,
        color=0x9B59B6,
    )

    if sent:

        state["FED_FUNDS_TARGET_RANGE"] = {
            "date": latest_date,
            "lower": latest_lower,
            "upper": latest_upper,
        }

        print(
            "💾 Federal Reserve state updated."
        )

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Also synchronise the FRED Fed Funds states.
        #
        # This prevents another Discord alert later when
        # FRED finally catches up with the official Fed
        # decision.
        # ----------------------------------------------------

        state["DFEDTARL"] = {
            "date": latest_date,
            "value": latest_lower,
        }

        state["DFEDTARU"] = {
            "date": latest_date,
            "value": latest_upper,
        }

        print(
            "🔄 FRED Fed Funds states synchronised."
        )

    else:

        print(
            "⚠️ Federal Reserve state NOT updated "
            "because Discord failed."
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    print("=" * 70)
    print("US ECONOMIC DATA MONITOR")
    print("=" * 70)

    state = load_state()

    # --------------------------------------------------------
    # 1. FRED ECONOMIC DATA
    # --------------------------------------------------------

    print("\n📊 Checking FRED economic data...\n")

    for series_id, name in SERIES.items():

        try:

            check_fred_series(
                series_id,
                name,
                state,
            )

        except Exception as exc:

            print(
                f"❌ Error processing "
                f"{series_id}: {exc}"
            )

    # --------------------------------------------------------
    # 2. FEDERAL RESERVE / FOMC
    # --------------------------------------------------------

    print(
        "\n🏦 Checking Federal Reserve "
        "FOMC target range...\n"
    )

    try:

        check_federal_reserve(state)

    except Exception as exc:

        print(
            f"❌ Error checking Federal Reserve: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # 3. SAVE STATE
    # --------------------------------------------------------

    save_state(state)

    print("\n💾 Economic state saved.")

    print("=" * 70)
    print("ECONOMIC MONITOR FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()
