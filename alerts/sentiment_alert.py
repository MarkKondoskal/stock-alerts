import os
import time
import math  
import warnings
import requests
import yfinance as yf
import json
from datetime import datetime, timezone

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Reads from the dedicated Market Sentiment webhook environment variable
DISCORD_SENTIMENT_WEBHOOK = os.environ.get("DISCORD_SENTIMENT_WEBHOOK")

# Volatility trigger levels
VIX_KEY_LEVELS = [12.0, 15.0, 25.0, 30.0, 35.0]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "sentiment_state.json")

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"vix": {}, "fear_greed_state": None}
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Could not load sentiment state: {e}. Starting with empty state.")
        return {"vix": {}, "fear_greed_state": None}

def save_state(state):
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)
    except OSError as e:
        print(f"Error saving sentiment state: {e}")

def post_webhook(payload):
    response = requests.post(DISCORD_SENTIMENT_WEBHOOK, json=payload, timeout=15)
    if response.status_code not in [200, 204]:
        raise RuntimeError(f"Discord returned HTTP {response.status_code}: {response.text}")


def send_discord_sentiment_alert(title, fields, color):
    """Generic embed dispatcher for Market Sentiment bot."""
    if not DISCORD_SENTIMENT_WEBHOOK:
        print("Error: DISCORD_SENTIMENT_WEBHOOK environment variable is missing.")
        return

    payload = {
        "username": "Market Sentiment",
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {"text": "Market Sentiment Alert"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }

    try:
        post_webhook(payload)
        print("Market Sentiment alert sent successfully.")
        return True
    except requests.RequestException as e:
        print(f"Failed to send sentiment alert: {e}")
    except RuntimeError as e:
        print(f"Failed to send sentiment alert: {e}")
    return False

def check_vix():
    """Checks today's VIX range and alerts once per key level per UTC day."""
    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()
    state.setdefault("vix", {})
    try:
        vix = yf.Ticker("^VIX")
        info = vix.fast_info

        current_val = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
        day_high = getattr(info, "day_high", None) or getattr(info, "dayHigh", None)
        day_low = getattr(info, "day_low", None) or getattr(info, "dayLow", None)

        values = (current_val, day_high, day_low)
        if any(v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in values):
            print("VIX Check -> Valid market data unavailable; no alert sent.")
            return

        print(f"VIX Check -> Last: {current_val:.2f} | Low: {day_low:.2f} | High: {day_high:.2f}")

        for level in VIX_KEY_LEVELS:
            level_key = str(level)
            already_alerted = state["vix"].get(level_key) == today
            if day_low <= level <= day_high and not already_alerted:
                print(f"TRIGGER: VIX level {level:.1f} touched today!")
                fields = [
                    {"name": "Key Level Touched", "value": f"**{level:.1f}**", "inline": True},
                    {"name": "Current VIX", "value": f"{current_val:.2f}", "inline": True},
                    {"name": "Day's Range", "value": f"{day_low:.2f} - {day_high:.2f}", "inline": True},
                ]
                sent = send_discord_sentiment_alert(
                    title=f"⚠️ VIX VOLATILITY ALERT: Level {level:.1f}",
                    fields=fields,
                    color=15158332
                )
                if sent:
                    state["vix"][level_key] = today
        # Remove entries from older days so the state file stays tiny.
        state["vix"] = {k: v for k, v in state["vix"].items() if v == today}
        save_state(state)
    except Exception as e:
        print(f"Error checking VIX: {e}")

def check_fear_and_greed():
    """Alerts only when the Fear & Greed state changes into/out of an extreme zone."""
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
            title = "🚨 MARKET SENTIMENT: EXTREME FEAR"
            state_text = "CRITICAL EXTREME FEAR"
            color = 15158332
        elif score >= 75 or "extreme greed" in rating:
            new_state = "extreme_greed"
            title = "🚨 MARKET SENTIMENT: EXTREME GREED"
            state_text = "CRITICAL EXTREME GREED"
            color = 3066993
        else:
            new_state = "normal"
            title = None

        previous_state = state.get("fear_greed_state")
        if new_state != previous_state:
            state["fear_greed_state"] = new_state
            if new_state != "normal":
                print(f"TRIGGER: Fear & Greed changed to {new_state}.")
                fields = [
                    {"name": "Fear & Greed Index", "value": f"**{score:.1f}**", "inline": True},
                    {"name": "Sentiment State", "value": state_text, "inline": True},
                ]
                send_discord_sentiment_alert(title=title, fields=fields, color=color)
            else:
                print("OK: Fear & Greed returned to normal territory. State reset.")
        else:
            print(f"OK: Fear & Greed remains {new_state}; no duplicate alert sent.")

        save_state(state)
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Error checking Fear & Greed Index: {e}")
    except Exception as e:
        print(f"Unexpected error checking Fear & Greed Index: {e}")

if __name__ == "__main__":
    print("Running Market Sentiment Check...")
    check_vix()
    check_fear_and_greed()
