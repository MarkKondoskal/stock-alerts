import json
import math
import os
import time
import warnings
from datetime import datetime, timezone

import requests
import yfinance as yf

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

DISCORD_SENTIMENT_WEBHOOK = os.environ.get("DISCORD_SENTIMENT_WEBHOOK")

# Directional VIX levels – alert only on first crossing each day
VIX_DOWN_LEVELS = [10.0, 12.0, 15.0]
VIX_UP_LEVELS   = [25.0, 30.0, 35.0, 40.0, 45.0, 50.0]

# Reset hysteresis offset: after an alert, require VIX to move this far back
# before allowing a new crossing alert.
RESET_OFFSET = 2.0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "sentiment_state.json")

# -----------------------------------------------------------------------------
# State management
# -----------------------------------------------------------------------------

def empty_state():
    return {
        "vix": {},
        "vix_last_price": None,
        "fear_greed_state": None,
    }

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise ValueError("State file does not contain a JSON object")
        state.setdefault("vix", {})
        state.setdefault("fear_greed_state", None)
        if "vix_last_price" not in state:
            state["vix_last_price"] = state.get("vix_last_close")
        state.pop("vix_last_close", None)
        return state
    except FileNotFoundError:
        return empty_state()
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
        print(f"Warning: Could not load sentiment state: {e}. Starting with empty state.")
        return empty_state()

def save_state(state):
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp_file, STATE_FILE)
    except OSError as e:
        print(f"Error saving sentiment state: {e}")
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass

# -----------------------------------------------------------------------------
# Discord
# -----------------------------------------------------------------------------

def post_webhook(payload):
    response = requests.post(
        DISCORD_SENTIMENT_WEBHOOK,
        json=payload,
        timeout=15,
    )
    if response.status_code not in (200, 204):
        raise RuntimeError(
            f"Discord returned HTTP {response.status_code}: {response.text}"
        )

def send_discord_sentiment_alert(title, fields, color):
    if not DISCORD_SENTIMENT_WEBHOOK:
        print("Error: DISCORD_SENTIMENT_WEBHOOK environment variable is missing.")
        return False

    payload = {
        "username": "Market Sentiment",
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {"text": "Market Sentiment Alert"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }

    try:
        post_webhook(payload)
        print("Market Sentiment alert sent successfully.")
        return True
    except (requests.RequestException, RuntimeError) as e:
        print(f"Failed to send sentiment alert: {e}")
        return False

# -----------------------------------------------------------------------------
# VIX
# -----------------------------------------------------------------------------

def valid_number(value):
    return (
        value is not None
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )

def check_vix():
    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()
    state.setdefault("vix", {})

    # ---- FORCE ALERT TEST ----
    print("⚠️ FORCE TEST: Simulating VIX crossing 15")
    fields = [
        {"name": "Level Crossed Down", "value": "📉 **15.0**", "inline": True},
        {"name": "Current VIX", "value": "14.80", "inline": True},
        {"name": "Previous VIX", "value": "16.20", "inline": True},
        {"name": "Day's Range", "value": "14.50 - 16.30", "inline": True},
    ]
    send_discord_sentiment_alert(
        title="🧪 TEST ALERT: VIX Crossed Below 15.0",
        fields=fields,
        color=3066993,
    )
    print("Test alert sent.")
    return
    # ---- END FORCE TEST ----

    try:
        vix = yf.Ticker("^VIX")
        info = vix.fast_info

        current_val = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
        day_high = getattr(info, "day_high", None) or getattr(info, "dayHigh", None)
        day_low = getattr(info, "day_low", None) or getattr(info, "dayLow", None)

        if not all(valid_number(v) for v in (current_val, day_high, day_low)):
            print("VIX Check -> Valid market data unavailable; no alert sent.")
            return

        current_val = float(current_val)
        day_high = float(day_high)
        day_low = float(day_low)

        previous_price = state.get("vix_last_price")
        if previous_price is not None and not valid_number(previous_price):
            previous_price = None

        print(
            f"VIX Check -> Current: {current_val:.2f} | "
            f"Previous: {previous_price:.2f} | "
            f"Low: {day_low:.2f} | High: {day_high:.2f}"
            if previous_price is not None
            else
            f"VIX Check -> Current: {current_val:.2f} | "
            f"Previous: N/A | Low: {day_low:.2f} | High: {day_high:.2f}"
        )

        if previous_price is None:
            print("VIX Check -> No previous price found; baseline initialized only.")
            state["vix_last_price"] = current_val
            save_state(state)
            return

        previous_price = float(previous_price)

        # ------------------------------------------------------------------
        # Process downward levels
        # ------------------------------------------------------------------
        for level in VIX_DOWN_LEVELS:
            level_key = f"down_{level:g}"
            already_alerted = state["vix"].get(level_key) == today

            crossed_down = (
                previous_price >= level
                and day_low <= level
            )

            if crossed_down:
                reset_condition = day_high > (level + RESET_OFFSET)
                if already_alerted and not reset_condition:
                    print(f"VIX down {level:.1f}: already alerted today, reset not met (high {day_high:.2f} <= {level+RESET_OFFSET:.1f})")
                    continue

                print(f"TRIGGER: VIX crossed DOWN through {level:.1f}!")
                fields = [
                    {"name": "Level Crossed Down", "value": f"📉 **{level:.1f}**", "inline": True},
                    {"name": "Current VIX", "value": f"{current_val:.2f}", "inline": True},
                    {"name": "Previous VIX", "value": f"{previous_price:.2f}", "inline": True},
                    {"name": "Day's Range", "value": f"{day_low:.2f} - {day_high:.2f}", "inline": True},
                ]
                sent = send_discord_sentiment_alert(
                    title=f"🟢 VIX VOLATILITY DROP: Crossed Below {level:.1f}",
                    fields=fields,
                    color=3066993,
                )
                if sent:
                    state["vix"][level_key] = today

        # ------------------------------------------------------------------
        # Process upward levels
        # ------------------------------------------------------------------
        for level in VIX_UP_LEVELS:
            level_key = f"up_{level:g}"
            already_alerted = state["vix"].get(level_key) == today

            crossed_up = (
                previous_price <= level
                and day_high >= level
            )

            if crossed_up:
                reset_condition = day_low < (level - RESET_OFFSET)
                if already_alerted and not reset_condition:
                    print(f"VIX up {level:.1f}: already alerted today, reset not met (low {day_low:.2f} >= {level-RESET_OFFSET:.1f})")
                    continue

                print(f"TRIGGER: VIX crossed UP through {level:.1f}!")
                fields = [
                    {"name": "Level Crossed Up", "value": f"📈 **{level:.1f}**", "inline": True},
                    {"name": "Current VIX", "value": f"{current_val:.2f}", "inline": True},
                    {"name": "Previous VIX", "value": f"{previous_price:.2f}", "inline": True},
                    {"name": "Day's Range", "value": f"{day_low:.2f} - {day_high:.2f}", "inline": True},
                ]
                sent = send_discord_sentiment_alert(
                    title=f"⚠️ VIX VOLATILITY SPIKE: Crossed Above {level:.1f}",
                    fields=fields,
                    color=15158332,
                )
                if sent:
                    state["vix"][level_key] = today

        state["vix_last_price"] = current_val

        # Keep only today's alert markers
        state["vix"] = {
            key: value
            for key, value in state["vix"].items()
            if value == today
        }

        save_state(state)

    except Exception as e:
        print(f"Error checking VIX: {e}")

# -----------------------------------------------------------------------------
# CNN Fear & Greed
# -----------------------------------------------------------------------------

def check_fear_and_greed():
    state = load_state()

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()

        data = res.json()
        score = float(data["fear_and_greed"]["score"])
        rating = str(data["fear_and_greed"]["rating"]).lower()

        if not math.isfinite(score):
            raise ValueError("Fear & Greed score is not finite")

        print(f"Fear & Greed Check -> Score: {score:.1f} | Rating: {rating}")

        if score <= 25 or "extreme fear" in rating:
            new_state = "extreme_fear"
            title = "🚨 EXTREME FEAR IN THE MARKET"
            color = 15158332
            fields = [
                {
                    "name": "📉 What This Means",
                    "value": "Investors are panicking – often signals oversold conditions and contrarian buying opportunity.",
                    "inline": False
                },
                {
                    "name": "Fear & Greed Score",
                    "value": f"**{score:.1f}** (Extreme Fear)",
                    "inline": True
                },
                {
                    "name": "Rating",
                    "value": rating.title(),
                    "inline": True
                },
            ]
            should_alert = True
        elif score >= 75 or "extreme greed" in rating:
            new_state = "extreme_greed"
            title = "🚨 EXTREME GREED IN THE MARKET"
            color = 3066993
            fields = [
                {
                    "name": "📈 What This Means",
                    "value": "Investors are euphoric – often signals overbought conditions and can be a warning sign of a pullback.",
                    "inline": False
                },
                {
                    "name": "Fear & Greed Score",
                    "value": f"**{score:.1f}** (Extreme Greed)",
                    "inline": True
                },
                {
                    "name": "Rating",
                    "value": rating.title(),
                    "inline": True
                },
            ]
            should_alert = True
        else:
            new_state = "normal"
            should_alert = False

        previous_state = state.get("fear_greed_state")

        if should_alert and new_state != previous_state:
            state["fear_greed_state"] = new_state
            print(f"TRIGGER: Fear & Greed changed to {new_state}.")
            send_discord_sentiment_alert(
                title=title,
                fields=fields,
                color=color,
            )
        elif new_state == "normal" and previous_state != "normal":
            print(f"Fear & Greed returned to normal (Score: {score:.1f}). No alert sent.")
            state["fear_greed_state"] = new_state
        else:
            print(f"OK: Fear & Greed remains {new_state}; no duplicate alert sent.")

        save_state(state)

    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Error checking Fear & Greed Index: {e}")
    except Exception as e:
        print(f"Unexpected error checking Fear & Greed Index: {e}")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running Market Sentiment Check...")
    check_vix()
    check_fear_and_greed()
