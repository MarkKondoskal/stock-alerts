import os
import time
import warnings
import requests
import yfinance as yf

warnings.filterwarnings("ignore", category=UserWarning)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# Volatility alert levels
VIX_KEY_LEVELS = [12.0, 15.0, 25.0, 30.0, 35.0]

def send_vix_alert(current_val, day_high, day_low, level):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")
        return

    payload = {
        "username": "Stock Monitor",
        "embeds": [
            {
                "title": f"⚠️ VIX VOLATILITY ALERT: Level {level:.1f} Breached",
                "color": 15158332,  # Warning Orange
                "fields": [
                    {"name": "Trigger Level", "value": f"{level:.1f}", "inline": True},
                    {"name": "Current VIX", "value": f"{current_val:.2f}", "inline": True},
                    {"name": "Day's Range", "value": f"{day_low:.2f} - {day_high:.2f}", "inline": True},
                ],
                "footer": {"text": "Market Volatility Tracker"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }

    response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if response.status_code not in [200, 204]:
        print(f"Failed to send VIX alert: {response.status_code}, {response.text}")

def check_vix():
    vix = yf.Ticker("^VIX")
    info = vix.fast_info

    current_val = info.get("lastPrice")
    day_high = info.get("dayHigh")
    day_low = info.get("dayLow")

    if None in (current_val, day_high, day_low):
        print("Error fetching VIX data.")
        return

    print(f"VIX Current: {current_val:.2f} | Low: {day_low:.2f} | High: {day_high:.2f}")

    # Alert if any threshold falls within today's trading range
    for level in VIX_KEY_LEVELS:
        if day_low <= level <= day_high:
            print(f"VIX Alert triggered for level {level}")
            send_vix_alert(current_val, day_high, day_low, level)

if __name__ == "__main__":
    print("Checking VIX level...")
    check_vix()
