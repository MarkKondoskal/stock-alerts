import os
import time
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def send_heartbeat():
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")
        return

    payload = {
        "username": "Stock Monitor",
        "embeds": [
            {
                "title": "🟢 SYSTEM HEARTBEAT",
                "description": "Stock price monitor is active and checking target alerts.",
                "color": 3066993,  # Blue/Green status color
                "footer": {"text": "Scheduled Status Ping"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }

    response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if response.status_code in [200, 204]:
        print("Heartbeat sent successfully.")
    else:
        print(f"Failed to send heartbeat: {response.status_code}, {response.text}")

if __name__ == "__main__":
    send_heartbeat()
