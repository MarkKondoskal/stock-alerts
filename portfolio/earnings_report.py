#!/usr/bin/env python3
import os
import sys
import json
import math
from datetime import datetime, date
import traceback

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

print("=== SCRIPT STARTED ===", flush=True)

try:
    import requests
    import yfinance as yf
except ImportError as e:
    print(f"❌ Import error: {e}", flush=True)
    sys.exit(1)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_PORTFOLIO_WEBHOOK")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "marks_portfolio.json")

print(f"DEBUG: WEBHOOK_URL set? {bool(WEBHOOK_URL)}", flush=True)
print(f"DEBUG: PORTFOLIO_FILE = {PORTFOLIO_FILE}", flush=True)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def safe_float(value, default=None):
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value):
            return default
        return value
    except (ValueError, TypeError):
        return default

def load_portfolio():
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Failed to load portfolio: {e}", flush=True)
        return {}

    return {
        ticker: value
        for ticker, value in data.items()
        if ticker != "closed_positions"
    }

def normalize_date(value):
    try:
        if hasattr(value, "tz_convert") and value.tzinfo is not None:
            value = value.tz_convert("UTC")
        return value.date()
    except Exception:
        return None

def format_percent(value):
    if value is None:
        return "N/A"
    return f"{value:+.0f}%"

# -----------------------------------------------------------------------------
# Earnings functions (same as before but with debug prints)
# -----------------------------------------------------------------------------

def get_latest_earnings(ticker):
    try:
        stock = yf.Ticker(ticker)
        earnings_dates = stock.get_earnings_dates(limit=12)
        if earnings_dates is None or earnings_dates.empty:
            return None

        df = earnings_dates.copy()
        if "Reported EPS" in df.columns:
            df = df[df["Reported EPS"].notna()]
        if df.empty:
            return None

        df = df.sort_index(ascending=False)
        row = df.iloc[0]
        earnings_date = normalize_date(df.index[0])
        if earnings_date is None:
            return None

        return {
            "date": earnings_date,
            "eps_actual": safe_float(row.get("Reported EPS")),
            "eps_estimate": safe_float(row.get("EPS Estimate")),
            "surprise_pct": safe_float(row.get("Surprise(%)")),
        }
    except Exception as e:
        print(f"⚠️ get_latest_earnings({ticker}) error: {e}", flush=True)
        return None

def get_revenue_data(ticker):
    revenue_actual = None
    revenue_previous = []
    revenue_estimate = None

    try:
        stock = yf.Ticker(ticker)
        financials = stock.quarterly_income_stmt
        if financials is not None and not financials.empty:
            revenue_row = None
            for name in ["Total Revenue", "Operating Revenue", "Revenue", "Revenues"]:
                if name in financials.index:
                    revenue_row = financials.loc[name]
                    break
            if revenue_row is not None:
                values = [safe_float(v) for v in revenue_row.tolist() if safe_float(v) is not None]
                if values:
                    revenue_actual = values[0]
                    revenue_previous = values[1:]

        try:
            revenue_estimates = stock.get_revenue_estimate()
            if revenue_estimates is not None and not revenue_estimates.empty:
                if "0q" in revenue_estimates.index:
                    revenue_estimate = safe_float(revenue_estimates.loc["0q", "avg"])
        except Exception as e:
            print(f"Revenue estimate unavailable for {ticker}: {e}", flush=True)

        revenue_qoq = None
        revenue_yoy = None
        if revenue_actual is not None and len(revenue_previous) >= 1:
            prev = revenue_previous[0]
            if prev not in (None, 0):
                revenue_qoq = ((revenue_actual - prev) / abs(prev)) * 100
        if revenue_actual is not None and len(revenue_previous) >= 4:
            prev_year = revenue_previous[3]
            if prev_year not in (None, 0):
                revenue_yoy = ((revenue_actual - prev_year) / abs(prev_year)) * 100

        return {
            "revenue_actual": revenue_actual,
            "revenue_estimate": revenue_estimate,
            "revenue_qoq": revenue_qoq,
            "revenue_yoy": revenue_yoy,
        }
    except Exception as e:
        print(f"⚠️ get_revenue_data({ticker}) error: {e}", flush=True)
        return {
            "revenue_actual": None,
            "revenue_estimate": None,
            "revenue_qoq": None,
            "revenue_yoy": None,
        }

def get_earnings_data(ticker):
    earnings = get_latest_earnings(ticker)
    if earnings is None:
        return None

    revenue = get_revenue_data(ticker)

    eps_actual = earnings["eps_actual"]
    eps_estimate = earnings["eps_estimate"]
    eps_beat_pct = None
    if eps_actual is not None and eps_estimate is not None and eps_estimate != 0:
        eps_beat_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100

    revenue_actual = revenue["revenue_actual"]
    revenue_estimate = revenue["revenue_estimate"]
    revenue_beat_pct = None
    if revenue_actual is not None and revenue_estimate is not None and revenue_estimate != 0:
        revenue_beat_pct = ((revenue_actual - revenue_estimate) / abs(revenue_estimate)) * 100

    return {
        "ticker": ticker,
        "earnings_date": earnings["date"],
        "eps_actual": eps_actual,
        "eps_estimate": eps_estimate,
        "eps_beat_pct": eps_beat_pct,
        "revenue_actual": revenue_actual,
        "revenue_estimate": revenue_estimate,
        "revenue_beat_pct": revenue_beat_pct,
        "eps_yoy": None,
        "eps_qoq": None,
        "revenue_yoy": revenue["revenue_yoy"],
        "revenue_qoq": revenue["revenue_qoq"],
    }

def add_eps_changes(ticker, data):
    try:
        stock = yf.Ticker(ticker)
        history = stock.get_earnings_history()
        if history is None or history.empty:
            return data
        history = history.copy()
        if "epsActual" in history.columns:
            history = history[history["epsActual"].notna()]
        if history.empty:
            return data
        history = history.sort_index(ascending=False)
        eps_values = [safe_float(v) for v in history["epsActual"].tolist() if safe_float(v) is not None]
        if len(eps_values) >= 2:
            cur, prev = eps_values[0], eps_values[1]
            if prev != 0:
                data["eps_qoq"] = ((cur - prev) / abs(prev)) * 100
        if len(eps_values) >= 5:
            cur, prev_year = eps_values[0], eps_values[4]
            if prev_year != 0:
                data["eps_yoy"] = ((cur - prev_year) / abs(prev_year)) * 100
    except Exception as e:
        print(f"⚠️ add_eps_changes({ticker}) error: {e}", flush=True)
    return data

# -----------------------------------------------------------------------------
# Formatting and Discord
# -----------------------------------------------------------------------------

def format_earnings_table(data):
    ticker = data["ticker"]
    lines = []
    lines.append(f"**{ticker}**")
    lines.append(f"*Reported: {data['earnings_date'].strftime('%Y-%m-%d')}*")
    lines.append("```")
    lines.append(f"{'Parameters':<15}{'Expected':>15}{'Actual':>15}{'Beat/Miss':>15}")
    lines.append("-" * 60)

    eps_actual = data["eps_actual"]
    eps_estimate = data["eps_estimate"]
    eps_beat = data["eps_beat_pct"]
    if eps_actual is not None:
        expected = f"{eps_estimate:.2f}" if eps_estimate is not None else "N/A"
        actual = f"{eps_actual:.2f}"
        if eps_beat is None:
            beat = "N/A"
        elif eps_beat > 0:
            beat = f"Beat +{eps_beat:.0f}%"
        elif eps_beat < 0:
            beat = f"Miss {eps_beat:.0f}%"
        else:
            beat = "In-line"
        lines.append(f"{'EPS':<15}{expected:>15}{actual:>15}{beat:>15}")

    revenue_actual = data["revenue_actual"]
    revenue_estimate = data["revenue_estimate"]
    revenue_beat = data["revenue_beat_pct"]
    if revenue_actual is not None:
        if revenue_actual >= 1e9:
            actual = f"{revenue_actual/1e9:.2f}B"
        elif revenue_actual >= 1e6:
            actual = f"{revenue_actual/1e6:.2f}M"
        else:
            actual = f"{revenue_actual:.2f}"

        if revenue_estimate is not None:
            if revenue_estimate >= 1e9:
                expected = f"{revenue_estimate/1e9:.2f}B"
            elif revenue_estimate >= 1e6:
                expected = f"{revenue_estimate/1e6:.2f}M"
            else:
                expected = f"{revenue_estimate:.2f}"
        else:
            expected = "N/A"

        if revenue_beat is None:
            beat = "N/A"
        elif revenue_beat > 0:
            beat = f"Beat +{revenue_beat:.0f}%"
        elif revenue_beat < 0:
            beat = f"Miss {revenue_beat:.0f}%"
        else:
            beat = "In-line"
        lines.append(f"{'Revenue':<15}{expected:>15}{actual:>15}{beat:>15}")

    lines.append("```")
    changes = []
    if data["eps_yoy"] is not None:
        changes.append(f"EPS YoY: {format_percent(data['eps_yoy'])}")
    if data["eps_qoq"] is not None:
        changes.append(f"EPS QoQ: {format_percent(data['eps_qoq'])}")
    if data["revenue_yoy"] is not None:
        changes.append(f"Revenue YoY: {format_percent(data['revenue_yoy'])}")
    if data["revenue_qoq"] is not None:
        changes.append(f"Revenue QoQ: {format_percent(data['revenue_qoq'])}")
    if changes:
        lines.append("  ".join(changes))

    return "\n".join(lines)

def post_to_discord(data):
    if not WEBHOOK_URL:
        print("❌ ERROR: DISCORD_PORTFOLIO_WEBHOOK is not set.", flush=True)
        return False

    ticker = data["ticker"]
    description = format_earnings_table(data)
    payload = {
        "username": "Earnings Bot",
        "embeds": [
            {
                "title": f"📈 {ticker} Earnings",
                "description": description,
                "color": 3447003
            }
        ]
    }

    webhook_url = WEBHOOK_URL
    if "?" not in webhook_url:
        webhook_url += "?wait=true"
    elif "wait=" not in webhook_url:
        webhook_url += "&wait=true"

    try:
        print(f"📨 Sending {ticker} earnings to Discord...", flush=True)
        response = requests.post(webhook_url, json=payload, timeout=20)
        print(f"Discord response for {ticker}: {response.status_code}", flush=True)
        if 200 <= response.status_code < 300:
            print(f"✅ {ticker} successfully sent.", flush=True)
            return True
        print(f"❌ Discord rejected {ticker}. Response: {response.text}", flush=True)
        return False
    except Exception as e:
        print(f"❌ Discord error for {ticker}: {e}", flush=True)
        return False

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print("=== ENTERED main() ===", flush=True)

    print("=" * 60, flush=True)
    print("PORTFOLIO EARNINGS REPORT", flush=True)
    print("=" * 60, flush=True)

    portfolio = load_portfolio()
    print(f"DEBUG: portfolio loaded, keys: {list(portfolio.keys())}", flush=True)

    if not portfolio:
        print("❌ No portfolio data found.", flush=True)
        return

    print(f"📊 Portfolio contains {len(portfolio)} holdings.", flush=True)
    print(f"📁 Portfolio file: {PORTFOLIO_FILE}", flush=True)

    report_mode = os.environ.get("REPORT_MODE", "all").lower()
    print(f"📋 Report mode: {report_mode}", flush=True)

    today = datetime.now().date()
    print(f"📅 Today: {today}", flush=True)
    print("=" * 60, flush=True)

    reports = []

    # --- TEST WITH AAPL FIRST (temporarily) ---
    print("\n--- TEST: AAPL ---", flush=True)
    aapl_data = get_earnings_data("AAPL")
    if aapl_data:
        print("✅ AAPL data fetched", flush=True)
        post_to_discord(aapl_data)
    else:
        print("❌ AAPL returned None", flush=True)

    # --- Process portfolio ---
    print("\n--- PROCESSING PORTFOLIO ---", flush=True)
    for ticker in portfolio.keys():
        print(f"\n🔍 Checking {ticker}...", flush=True)
        data = get_earnings_data(ticker)
        if data is None:
            print(f"❌ {ticker}: NO EARNINGS DATA", flush=True)
            continue

        print(f"✅ {ticker}: earnings date = {data.get('earnings_date')}", flush=True)

        if report_mode == "today":
            earnings_date = data.get("earnings_date")
            if earnings_date != today:
                print(f"⏭️ {ticker}: did not report today → skipping", flush=True)
                continue
            print(f"🚨 {ticker}: REPORTED TODAY → adding to report", flush=True)
        else:
            print(f"📈 {ticker}: adding to manual ALL report", flush=True)

        reports.append(data)

    # Summary
    print("\n" + "=" * 60, flush=True)
    print(f"TOTAL REPORTS: {len(reports)}", flush=True)
    print("=" * 60, flush=True)

    if not reports:
        print("❌ No companies matched the report criteria.", flush=True)
        if report_mode == "today":
            print("This is normal if none of your holdings reported today.", flush=True)
        return

    # Send reports
    print("\n" + "=" * 60, flush=True)
    print("SENDING EARNINGS REPORTS TO DISCORD", flush=True)
    print("=" * 60, flush=True)

    successful = 0
    failed = 0
    for data in reports:
        ticker = data["ticker"]
        success = post_to_discord(data)
        if success:
            successful += 1
        else:
            failed += 1

    print("\n" + "=" * 60, flush=True)
    print("DISCORD REPORT SUMMARY", flush=True)
    print("=" * 60, flush=True)
    print(f"Successful: {successful}", flush=True)
    print(f"Failed:     {failed}", flush=True)
    print(f"Total:      {len(reports)}", flush=True)
    if failed == 0:
        print("🎉 All earnings reports sent successfully.", flush=True)
    else:
        print("⚠️ Some earnings reports failed to send.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Unhandled exception in main: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
    print("=== SCRIPT FINISHED ===", flush=True)
