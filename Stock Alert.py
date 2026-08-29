import os
import time
import warnings
import requests
import yfinance as yf

# Suppress internal pandas/yfinance warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*utcnow.*")

# Fetch Webhook URL from GitHub Environment Secrets
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

WATCHLIST = {
    "RDW": [8.0],
    "APP": [300.0],
    "GOOG": [300.0],
    "AMKR": [42.0, 38.5],
    "CRDO": [140.0],
    "IREN": [28.5],
    "NBIS": [170.0],
    "SNPS": [380.0],
    "VOYG": [30.0],
    "KEEL": [3.0, 2.5],
    "CRWV": [65.0],
    "ASTS": [55.0],
    "APLD": [22.0],
    "META": [525.0],
    "ZETA": [25.0],
    "PGY": [18.0],
}

def send_discord_alert(symbol, current_price, target_price):
    if not DISCORD_WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")
        return

    payload = {
        "username": "Stock Monitor",
        "embeds": [
            {
                "title": f"🚨 PRICE TARGET ALERT: {symbol}",
                "color": 5763719,
                "fields": [
                    {"name": "Current Price", "value": f"${current_price:.2f}", "inline": True},
                    {"name": "Target Price", "value": f"${target_price:.2f}", "inline": True},
                ],
                "footer": {"text": "Stock Price Tracker"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        ]
    }
    
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if response.status_code not in [200, 204]:
        print(f"Failed to send alert: {response.status_code}, {response.text}")

def check_prices():
    tickers_str = " ".join(WATCHLIST.keys())
    data = yf.Tickers(tickers_str)
    
    for symbol, targets in WATCHLIST.items():
        try:
            price = data.tickers[symbol].fast_info['lastPrice']
            if price is None:
                continue
                
            for target in targets:
                if price <= target:
                    print(f"ALERT: {symbol} price ${price:.2f} <= target ${target:.2f}")
                    send_discord_alert(symbol, price, target)
                else:
                    print(f"OK: {symbol} (${price:.2f}) > target (${target:.2f})")
                    
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

if __name__ == "__main__":
    print("Checking prices...")
    check_prices()
