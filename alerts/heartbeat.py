import os
import time
import requests

# Try to get webhook from environment – supports multiple possible names
DISCORD_WEBHOOK_URL = (
    os.environ.get("DISCORD_WEBHOOK_URL") or
    os.environ.get("DISCORD_PORTFOLIO_TEST_WEBHOOK") or
    os.environ.get("DISCORD_STOCK_WEBHOOK")
)

def send_heartbeat():
    if not DISCORD_WEBHOOK_URL:
        print("Error: No Discord webhook URL found in environment.")
        return

    payload = {
        "username": "Stock Monitor",
        "embeds": [
            {
                "title": "🟢 SYSTEM HEARTBEAT",
                "description": "Stock price monitor is active and checking target alerts.",
                "color": 3066993,
                "footer": {"text": "Scheduled Status Ping"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code in [200, 204]:
            print("Heartbeat sent successfully.")
        else:
            print(f"Failed to send heartbeat: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error sending heartbeat: {e}")

if __name__ == "__main__":
    send_heartbeat()
