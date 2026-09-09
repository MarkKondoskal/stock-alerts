import os
import json
import math
from datetime import datetime, date

import requests
import yfinance as yf


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

WEBHOOK_URL = os.environ.get("DISCORD_PORTFOLIO_WEBHOOK")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "marks_portfolio.json")


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
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    return {
        ticker: value
        for ticker, value in data.items()
        if ticker != "closed_positions"
    }


def normalize_date(value):
    """
    Convert a Yahoo/yfinance datetime into a normal date.

    Handles both timezone-aware and timezone-naive timestamps.
    """
    try:
        timestamp = value

        if hasattr(timestamp, "tz_convert"):
            if timestamp.tzinfo is not None:
                timestamp = timestamp.tz_convert("UTC")

        return timestamp.date()

    except Exception:
        return None


def format_percent(value):
    if value is None:
        return "N/A"

    return f"{value:+.0f}%"


# -----------------------------------------------------------------------------
# Earnings date
# -----------------------------------------------------------------------------

def get_latest_earnings(ticker):
    """
    Get the most recent reported earnings event for a ticker.

    yfinance's get_earnings_dates() contains historical and future earnings
    dates and reported EPS information.
    """

    try:
        stock = yf.Ticker(ticker)

        earnings_dates = stock.get_earnings_dates(limit=12)

        if earnings_dates is None or earnings_dates.empty:
            return None

        # Make a copy so we don't modify yfinance's dataframe.
        df = earnings_dates.copy()

        # We only want earnings that have actually been reported.
        if "Reported EPS" in df.columns:
            df = df[df["Reported EPS"].notna()]

        if df.empty:
            return None

        # Newest reported event first.
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
        print(f"Error getting earnings date for {ticker}: {e}")
        return None


# -----------------------------------------------------------------------------
# Revenue
# -----------------------------------------------------------------------------

def get_revenue_data(ticker):
    """
    Get quarterly revenue data.

    Revenue estimates are obtained from yfinance's revenue_estimate
    endpoint when available.

    Revenue actual comes from the latest quarterly income statement.
    """

    revenue_actual = None
    revenue_previous = []
    revenue_estimate = None

    try:
        stock = yf.Ticker(ticker)

        # ---------------------------------------------------------------------
        # Actual quarterly revenue
        # ---------------------------------------------------------------------

        financials = stock.quarterly_income_stmt

        if financials is not None and not financials.empty:

            revenue_row = None

            for name in [
                "Total Revenue",
                "Operating Revenue",
                "Revenue",
                "Revenues",
            ]:
                if name in financials.index:
                    revenue_row = financials.loc[name]
                    break

            if revenue_row is not None:

                values = [
                    safe_float(value)
                    for value in revenue_row.tolist()
                ]

                values = [
                    value for value in values
                    if value is not None
                ]

                if values:
                    revenue_actual = values[0]
                    revenue_previous = values[1:]

        # ---------------------------------------------------------------------
        # Revenue estimate
        # ---------------------------------------------------------------------

        try:
            revenue_estimates = stock.get_revenue_estimate()

            if revenue_estimates is not None and not revenue_estimates.empty:

                # 0q = current quarter estimate
                if "0q" in revenue_estimates.index:

                    revenue_estimate = safe_float(
                        revenue_estimates.loc["0q", "avg"]
                    )

        except Exception as e:
            print(f"Revenue estimate unavailable for {ticker}: {e}")

        # ---------------------------------------------------------------------
        # QoQ / YoY
        # ---------------------------------------------------------------------

        revenue_qoq = None
        revenue_yoy = None

        if revenue_actual is not None and len(revenue_previous) >= 1:

            previous = revenue_previous[0]

            if previous not in (None, 0):
                revenue_qoq = (
                    (revenue_actual - previous)
                    / abs(previous)
                ) * 100

        if revenue_actual is not None and len(revenue_previous) >= 4:

            previous_year = revenue_previous[3]

            if previous_year not in (None, 0):
                revenue_yoy = (
                    (revenue_actual - previous_year)
                    / abs(previous_year)
                ) * 100

        return {
            "revenue_actual": revenue_actual,
            "revenue_estimate": revenue_estimate,
            "revenue_qoq": revenue_qoq,
            "revenue_yoy": revenue_yoy,
        }

    except Exception as e:
        print(f"Error getting revenue for {ticker}: {e}")

        return {
            "revenue_actual": None,
            "revenue_estimate": None,
            "revenue_qoq": None,
            "revenue_yoy": None,
        }


# -----------------------------------------------------------------------------
# Complete earnings data
# -----------------------------------------------------------------------------

def get_earnings_data(ticker):
    """
    Get complete earnings information for one company.
    """

    earnings = get_latest_earnings(ticker)

    if earnings is None:
        return None

    revenue = get_revenue_data(ticker)

    eps_actual = earnings["eps_actual"]
    eps_estimate = earnings["eps_estimate"]

    eps_beat_pct = None

    if (
        eps_actual is not None
        and eps_estimate is not None
        and eps_estimate != 0
    ):
        eps_beat_pct = (
            (eps_actual - eps_estimate)
            / abs(eps_estimate)
        ) * 100

    revenue_actual = revenue["revenue_actual"]
    revenue_estimate = revenue["revenue_estimate"]

    revenue_beat_pct = None

    if (
        revenue_actual is not None
        and revenue_estimate is not None
        and revenue_estimate != 0
    ):
        revenue_beat_pct = (
            (revenue_actual - revenue_estimate)
            / abs(revenue_estimate)
        ) * 100

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


# -----------------------------------------------------------------------------
# EPS historical changes
# -----------------------------------------------------------------------------

def add_eps_changes(ticker, data):
    """
    Add EPS QoQ and YoY using yfinance earnings history.
    """

    try:
        stock = yf.Ticker(ticker)

        history = stock.get_earnings_history()

        if history is None or history.empty:
            return data

        history = history.copy()

        # Only actual reported earnings.
        if "epsActual" in history.columns:
            history = history[history["epsActual"].notna()]

        if history.empty:
            return data

        history = history.sort_index(ascending=False)

        eps_values = [
            safe_float(value)
            for value in history["epsActual"].tolist()
        ]

        eps_values = [
            value for value in eps_values
            if value is not None
        ]

        if len(eps_values) >= 2:
            current = eps_values[0]
            previous = eps_values[1]

            if previous != 0:
                data["eps_qoq"] = (
                    (current - previous)
                    / abs(previous)
                ) * 100

        if len(eps_values) >= 5:
            current = eps_values[0]
            previous_year = eps_values[4]

            if previous_year != 0:
                data["eps_yoy"] = (
                    (current - previous_year)
                    / abs(previous_year)
                ) * 100

    except Exception as e:
        print(f"Error getting EPS history for {ticker}: {e}")

    return data


# -----------------------------------------------------------------------------
# Formatting
# -----------------------------------------------------------------------------

def format_earnings_table(data):
    ticker = data["ticker"]

    lines = []

    lines.append(f"**{ticker}**")
    lines.append(
        f"*Earnings date: {data['earnings_date'].strftime('%Y-%m-%d')}*"
    )

    lines.append("```")

    lines.append(
        f"{'Parameters':<15}"
        f"{'Expected':>15}"
        f"{'Actual':>15}"
        f"{'Beat/Miss':>15}"
    )

    lines.append("-" * 60)

    # -------------------------------------------------------------------------
    # EPS
    # -------------------------------------------------------------------------

    eps_actual = data["eps_actual"]
    eps_estimate = data["eps_estimate"]
    eps_beat = data["eps_beat_pct"]

    if eps_actual is not None:

        expected = (
            f"{eps_estimate:.2f}"
            if eps_estimate is not None
            else "N/A"
        )

        actual = f"{eps_actual:.2f}"

        if eps_beat is None:
            beat = "N/A"

        elif eps_beat > 0:
            beat = f"Beat +{eps_beat:.0f}%"

        elif eps_beat < 0:
            beat = f"Miss {eps_beat:.0f}%"

        else:
            beat = "In-line"

        lines.append(
            f"{'EPS':<15}"
            f"{expected:>15}"
            f"{actual:>15}"
            f"{beat:>15}"
        )

    # -------------------------------------------------------------------------
    # Revenue
    # -------------------------------------------------------------------------

    revenue_actual = data["revenue_actual"]
    revenue_estimate = data["revenue_estimate"]
    revenue_beat = data["revenue_beat_pct"]

    if revenue_actual is not None:

        if revenue_actual >= 1e9:
            actual = f"{revenue_actual / 1e9:.2f}B"
        elif revenue_actual >= 1e6:
            actual = f"{revenue_actual / 1e6:.2f}M"
        else:
            actual = f"{revenue_actual:.2f}"

        if revenue_estimate is not None:

            if revenue_estimate >= 1e9:
                expected = f"{revenue_estimate / 1e9:.2f}B"
            elif revenue_estimate >= 1e6:
                expected = f"{revenue_estimate / 1e6:.2f}M"
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

        lines.append(
            f"{'Revenue':<15}"
            f"{expected:>15}"
            f"{actual:>15}"
            f"{beat:>15}"
        )

    lines.append("```")

    # -------------------------------------------------------------------------
    # Growth
    # -------------------------------------------------------------------------

    changes = []

    if data["eps_yoy"] is not None:
        changes.append(
            f"EPS YoY: {format_percent(data['eps_yoy'])}"
        )

    if data["eps_qoq"] is not None:
        changes.append(
            f"EPS QoQ: {format_percent(data['eps_qoq'])}"
        )

    if data["revenue_yoy"] is not None:
        changes.append(
            f"Revenue YoY: {format_percent(data['revenue_yoy'])}"
        )

    if data["revenue_qoq"] is not None:
        changes.append(
            f"Revenue QoQ: {format_percent(data['revenue_qoq'])}"
        )

    if changes:
        lines.append("  ".join(changes))

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Discord
# -----------------------------------------------------------------------------

def post_to_discord(description, color=3447003):
    if not WEBHOOK_URL:
        print("❌ ERROR: DISCORD_PORTFOLIO_WEBHOOK is not set.")
        print("Check GitHub Settings → Secrets and variables → Actions.")
        return False

    print("🔎 Discord webhook variable is present.")
    print(f"Message length: {len(description)} characters")

    payload = {
        "username": "Earnings Bot",
        "embeds": [{
            "title": "📈 Portfolio Earnings Highlights",
            "description": description,
            "color": color
        }]
    }

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            timeout=15
        )

        print(f"Discord HTTP status: {response.status_code}")

        if response.status_code >= 200 and response.status_code < 300:
            print("✅ Earnings report successfully sent to Discord.")
            return True

        print("❌ Discord rejected the webhook.")
        print(f"Response: {response.text}")

        return False

    except requests.exceptions.Timeout:
        print("❌ Discord request timed out.")
        return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Discord request failed: {e}")
        return False

    except Exception as e:
        print(f"❌ Unexpected Discord error: {e}")
        return False

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():

    portfolio = load_portfolio()

    if not portfolio:
        print("No portfolio data found.")
        return

    # GitHub Actions can provide:
    #
    #   REPORT_MODE=all
    #
    # or
    #
    #   REPORT_MODE=today
    #
    report_mode = os.environ.get("REPORT_MODE", "all").lower()

    today = date.today()

    reports = []

    for ticker in portfolio.keys():

        print(f"Checking {ticker}...")

        data = get_earnings_data(ticker)

        if data is None:
            print(f"{ticker}: no earnings data found.")
            continue

        data = add_eps_changes(ticker, data)

        earnings_date = data["earnings_date"]

        print(
            f"{ticker}: latest earnings = "
            f"{earnings_date}"
        )

        # ---------------------------------------------------------------------
        # AUTOMATIC MODE
        #
        # Only include companies whose latest earnings report is TODAY.
        # ---------------------------------------------------------------------

        if report_mode == "today":

            if earnings_date != today:
                print(
                    f"{ticker}: not reported today -> skipping."
                )
                continue

        # ---------------------------------------------------------------------
        # MANUAL MODE
        #
        # Include every portfolio company.
        # ---------------------------------------------------------------------

        reports.append(data)

    # -------------------------------------------------------------------------
    # Nothing to report
    # -------------------------------------------------------------------------

    if not reports:

        if report_mode == "today":
            print("No portfolio companies reported earnings today.")
            return

        print("No earnings data available.")
        return

    # -------------------------------------------------------------------------
    # Build Discord message
    # -------------------------------------------------------------------------

    description = ""

    for data in reports:

        description += (
            format_earnings_table(data)
            + "\n\n"
        )

    post_to_discord(description)


if __name__ == "__main__":
    main()
