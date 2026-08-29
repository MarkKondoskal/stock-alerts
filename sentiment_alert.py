import os
import time
import warnings
import requests
import yfinance as yf

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Reads from the dedicated Market Sentiment webhook environment variable
DISCORD_SENTIMENT_WEBHOOK = os.environ.get("DISCORD_SENTIMENT_WEBHOOK")

# Volatility trigger levels
VIX_KEY_LEVELS = [12.0, 15.0, 25.0, 30.0, 35.0]

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

    response = requests.post(DISCORD_SENTIMENT_WEBHOOK, json=payload)
    if response.status_code not in [200, 204]:
        print(f"Failed to send sentiment alert: {response.status_code}, {response.text}")
    else:
        print("Market Sentiment alert sent successfully.")

def check_vix():
    """Checks if today's VIX range touched any key levels."""
    try:
        vix = yf.Ticker("^VIX")
        info = vix.fast_info

        current_val = getattr(info, 'last_price', None) or getattr(info, 'lastPrice', None)
        day_high = getattr(info, 'day_high', None) or getattr(info, 'dayHigh', None)
        day_low = getattr(info, 'day_low', None) or getattr(info, 'dayLow', None)

        if None in (current_val, day_high, day_low):
            print("VIX Check -> Data currently unavailable (Market closed).")
            return

        print(f"VIX Check -> Last: {current_val:.2f} | Low: {day_low:.2f} | High: {day_high:.2f}")

        for level in VIX_KEY_LEVELS:
            if day_low <= level <= day_high:
                print(f"TRIGGER: VIX level {level:.1f} breached today!")
                fields = [
                    {"name": "Key Level Breached", "value": f"**{level:.1f}**", "inline": True},
                    {"name": "Current VIX", "value": f"${current_val:.2f}", "inline": True},
                    {"name": "Day's Range", "value": f"{day_low:.2f} - {day_high:.2f}", "inline": True},
                ]
                send_discord_sentiment_alert(
                    title=f"⚠️ VIX VOLATILITY ALERT: Level {level:.1f}",
                    fields=fields,
                    color=15158332 # Orange
                )
    except Exception as e:
        print(f"Error checking VIX: {e}")

def check_fear_and_greed():
    """Queries CNN Fear & Greed endpoint directly."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        res = requests.get(url, headers=headers, timeout=10)
        
        if res.status_code != 200:
            print(f"Fear & Greed fetch failed with status {res.status_code}")
            return

        data = res.json()
        score = float(data["fear_and_greed"]["score"])
        rating = str(data["fear_and_greed"]["rating"]).lower()

        print(f"Fear & Greed Check -> Score: {score:.1f} | Rating: {rating}")

        if score <= 25 or "extreme fear" in rating:
            print("TRIGGER: CNN Fear & Greed in Extreme Fear territory!")
            fields = [
                {"name": "Fear & Greed Index", "value": f"**{score:.1f}**", "inline": True},
                {"name": "Sentiment State", "value": "CRITICAL EXTREME FEAR", "inline": True},
            ]
            send_discord_sentiment_alert(
                title="🚨 MARKET SENTIMENT: EXTREME FEAR",
                fields=fields,
                color=15158332 # Red
            )
        elif score >= 75 or "extreme greed" in rating:
            print("TRIGGER: CNN Fear & Greed in Extreme Greed territory!")
            fields = [
                {"name": "Fear & Greed Index", "value": f"**{score:.1f}**", "inline": True},
                {"name": "Sentiment State", "value": "CRITICAL EXTREME GREED", "inline": True},
            ]
            send_discord_sentiment_alert(
                title="🚨 MARKET SENTIMENT: EXTREME GREED",
                fields=fields,
                color=3066993 # Green
            )
        else:
            print("OK: Fear & Greed is in normal territory (No alert sent).")

    except Exception as e:
        print(f"Error checking Fear & Greed Index: {e}")

if __name__ == "__main__":
    print("Running Market Sentiment Check...")
    check_vix()
    check_fear_and_greed()
