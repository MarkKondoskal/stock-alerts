import os
import json
import math
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

def safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def load_portfolio():
    try:
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    # Keep only tickers (ignore closed_positions)
    return {k: v for k, v in data.items() if k != "closed_positions"}

# -----------------------------------------------------------------------------
# Fetch earnings data for a single ticker
# -----------------------------------------------------------------------------

def get_earnings_data(ticker):
    """
    Returns a dict with EPS and Revenue actual, expected, beat%, and YoY/QoQ changes.
    If data is incomplete, returns None.
    """
    try:
        stock = yf.Ticker(ticker)
        
        # ---- EPS actual and estimate from quarterly earnings ----
        earnings = stock.earnings  # DataFrame with epsActual, epsEstimate
        if earnings is None or earnings.empty:
            return None
        
        latest = earnings.iloc[0]
        eps_actual = safe_float(latest.get('epsActual'))
        eps_estimate = safe_float(latest.get('epsEstimate'))
        if eps_actual == 0 or eps_estimate == 0:
            return None  # incomplete data
        
        # ---- Revenue actual from quarterly financials ----
        q_fin = stock.quarterly_financials
        revenue_actual = None
        if q_fin is not None and not q_fin.empty:
            # Try common row names for revenue
            rev_row = None
            for name in ['Total Revenue', 'Revenue', 'Revenues']:
                if name in q_fin.index:
                    rev_row = q_fin.loc[name]
                    break
            if rev_row is not None:
                revenue_actual = safe_float(rev_row.iloc[0])
        
        # ---- Revenue estimate from earnings_estimate ----
        est = stock.earnings_estimate
        revenue_estimate = None
        if est is not None:
            rev_est = est.get('revenue', {}).get('avg')
            if rev_est:
                revenue_estimate = safe_float(rev_est)
        
        # ---- Beat/Miss percentages ----
        eps_beat_pct = ((eps_actual - eps_estimate) / abs(eps_estimate) * 100) if eps_estimate != 0 else None
        rev_beat_pct = None
        if revenue_actual and revenue_estimate and revenue_estimate != 0:
            rev_beat_pct = ((revenue_actual - revenue_estimate) / abs(revenue_estimate) * 100)
        
        # ---- YoY and QoQ changes ----
        # EPS: compare with previous quarter (index 1) and same quarter last year (index 4)
        eps_qoq = None
        eps_yoy = None
        if len(earnings) >= 2:
            prev = safe_float(earnings.iloc[1].get('epsActual'))
            if prev != 0:
                eps_qoq = ((eps_actual - prev) / abs(prev)) * 100
        if len(earnings) >= 5:
            prev_year = safe_float(earnings.iloc[4].get('epsActual'))
            if prev_year != 0:
                eps_yoy = ((eps_actual - prev_year) / abs(prev_year)) * 100
        
        # Revenue: use quarterly_financials for previous quarters
        revenue_qoq = None
        revenue_yoy = None
        if revenue_actual and rev_row is not None and len(rev_row) >= 2:
            prev_rev = safe_float(rev_row.iloc[1])
            if prev_rev != 0:
                revenue_qoq = ((revenue_actual - prev_rev) / abs(prev_rev)) * 100
        if revenue_actual and rev_row is not None and len(rev_row) >= 5:
            prev_year_rev = safe_float(rev_row.iloc[4])
            if prev_year_rev != 0:
                revenue_yoy = ((revenue_actual - prev_year_rev) / abs(prev_year_rev)) * 100
        
        return {
            'ticker': ticker,
            'eps_actual': eps_actual,
            'eps_estimate': eps_estimate,
            'eps_beat_pct': eps_beat_pct,
            'revenue_actual': revenue_actual,
            'revenue_estimate': revenue_estimate,
            'rev_beat_pct': rev_beat_pct,
            'eps_yoy': eps_yoy,
            'eps_qoq': eps_qoq,
            'revenue_yoy': revenue_yoy,
            'revenue_qoq': revenue_qoq,
        }
    except Exception as e:
        print(f"Error fetching earnings for {ticker}: {e}")
        return None

# -----------------------------------------------------------------------------
# Formatting for Discord (matches the image style)
# -----------------------------------------------------------------------------

def format_earnings_table(data):
    if not data:
        return ""
    ticker = data['ticker']
    lines = [f"**{ticker}**"]
    lines.append("```")
    lines.append(f"{'Parameters':<15} {'Expected ($)':>15} {'Actual ($)':>12} {'Beat/Miss':>12}")
    lines.append("-" * 60)
    
    # EPS
    eps_actual = data['eps_actual']
    eps_est = data['eps_estimate']
    eps_beat = data['eps_beat_pct']
    if eps_actual and eps_est:
        beat_str = f"Beat +{eps_beat:.0f}%" if eps_beat and eps_beat > 0 else f"Miss {eps_beat:.0f}%" if eps_beat and eps_beat < 0 else "In-line"
        lines.append(f"{'EPS':<15} {eps_est:>15.2f} {eps_actual:>12.2f} {beat_str:>12}")
    else:
        lines.append(f"{'EPS':<15} {'N/A':>15} {'N/A':>12} {'N/A':>12}")
    
    # Revenue
    rev_actual = data['revenue_actual']
    rev_est = data['revenue_estimate']
    rev_beat = data['rev_beat_pct']
    if rev_actual and rev_est:
        # Format in billions if > 1e9
        if rev_actual > 1e9:
            rev_actual_str = f"{rev_actual/1e9:.2f}B"
            rev_est_str = f"{rev_est/1e9:.2f}B"
        else:
            rev_actual_str = f"{rev_actual:.2f}"
            rev_est_str = f"{rev_est:.2f}"
        beat_str = f"Beat +{rev_beat:.0f}%" if rev_beat and rev_beat > 0 else f"Miss {rev_beat:.0f}%" if rev_beat and rev_beat < 0 else "In-line"
        lines.append(f"{'Revenue':<15} {rev_est_str:>15} {rev_actual_str:>12} {beat_str:>12}")
    else:
        lines.append(f"{'Revenue':<15} {'N/A':>15} {'N/A':>12} {'N/A':>12}")
    
    lines.append("```")
    
    # YoY / QoQ changes
    changes = []
    if data['eps_yoy'] is not None:
        changes.append(f"EPS YoY: {data['eps_yoy']:+.0f}%")
    if data['eps_qoq'] is not None:
        changes.append(f"EPS QoQ: {data['eps_qoq']:+.0f}%")
    if data['revenue_yoy'] is not None:
        changes.append(f"Revenue YoY: {data['revenue_yoy']:+.0f}%")
    if data['revenue_qoq'] is not None:
        changes.append(f"Revenue QoQ: {data['revenue_qoq']:+.0f}%")
    if changes:
        lines.append("  ".join(changes))
    else:
        lines.append("(No change data available)")
    
    return "\n".join(lines)

# -----------------------------------------------------------------------------
# Post to Discord
# -----------------------------------------------------------------------------

def post_to_discord(description, color=3447003):
    if not WEBHOOK_URL:
        print("Error: DISCORD_PORTFOLIO_WEBHOOK not set.")
        return
    
    payload = {
        "username": "Earnings Bot",
        "embeds": [{
            "title": "📈 Portfolio Earnings Highlights",
            "description": description,
            "color": color
        }]
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print("Earnings report sent to Discord.")
    except Exception as e:
        print(f"Discord error: {e}")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    portfolio = load_portfolio()
    if not portfolio:
        print("No portfolio data found.")
        return
    
    full_description = ""
    for ticker in portfolio.keys():
        data = get_earnings_data(ticker)
        if data:
            full_description += format_earnings_table(data) + "\n\n"
        else:
            full_description += f"_{ticker}: earnings data unavailable_\n\n"
    
    if not full_description:
        full_description = "No earnings data could be retrieved for any holdings."
    
    post_to_discord(full_description)

if __name__ == "__main__":
    main()
