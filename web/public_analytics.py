"""Read-only, percentage-only portfolio analytics. No portfolio quantities leave this module.

Market-value allocations use latest available adjusted close. Performance is a
holdings-weighted PRICE-RETURN PROXY, not a brokerage/account TWR: cash,
dividends, FX, fees and fully closed historical holdings are unavailable.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from threading import Lock
import math
import time

PERIODS = {"1D": 1, "1W": 7, "1M": 30, "3M": 90, "6M": 183,
           "YTD": None, "1Y": 365, "3Y": 1096, "ALL": 3650}
SECTORS = {
    "TSM": "Technology", "SPGI": "Financials", "CRM": "Technology",
    "DUOL": "Consumer Discretionary", "MSFT": "Technology", "AMD": "Technology",
    "ADBE": "Technology", "ORCL": "Technology", "APP": "Technology",
    "GOOG": "Communication Services", "AMZN": "Consumer Discretionary",
    "ASML": "Technology", "ZETA": "Technology", "NVO": "Health Care",
    "META": "Communication Services", "UBER": "Industrials", "MA": "Financials",
    "VST": "Utilities", "PGY": "Financials", "SOFI": "Financials",
    "CELH": "Consumer Staples",
}
_cache = {}
_lock = Lock()


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


def _load_history(tickers, start, intraday):
    import yfinance as yf
    import pandas as pd
    tickers = sorted(set(tickers) | {"SPY"})
    if intraday == "1D":
        raw = yf.download(tickers, period="1d", interval="5m", auto_adjust=True,
                          progress=False, threads=True, group_by="ticker")
    elif intraday == "1W":
        raw = yf.download(tickers, period="5d", interval="60m", auto_adjust=True,
                          progress=False, threads=True, group_by="ticker")
    else:
        raw = yf.download(tickers, start=start.isoformat(),
                          end=(date.today() + timedelta(days=1)).isoformat(),
                          interval="1d", auto_adjust=True, progress=False,
                          threads=True, group_by="ticker")
    if raw is None or raw.empty:
        return {}
    output = {}
    for ticker in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if ticker in raw.columns.get_level_values(0):
                    series = raw[ticker]["Close"]
                else:
                    series = raw["Close"][ticker]
            else:
                series = raw["Close"] if len(tickers) == 1 else None
            if series is None:
                continue
            vals = {}
            for stamp, value in series.dropna().items():
                value = _number(value)
                if value > 0:
                    # Intraday timestamps are ISO UTC; daily are date-only.
                    if intraday:
                        ts = stamp.isoformat()
                    else:
                        ts = stamp.date().isoformat()
                    vals[ts] = value
            if vals:
                output[ticker] = vals
        except (KeyError, ValueError, TypeError):
            continue
    return output


def _positions(portfolio):
    positions = {}
    for ticker, item in portfolio.items():
        if not isinstance(item, dict) or ticker == "closed_positions":
            continue
        shares = _number(item.get("shares"))
        if shares <= 0:
            continue
        transactions = []
        for tx in item.get("transactions", []):
            try:
                day = date.fromisoformat(str(tx["date"])[:10])
                direction = str(tx.get("action", "")).upper()
                units = _number(tx.get("shares"))
                if direction in ("BUY", "SELL") and units > 0:
                    transactions.append((day, units if direction == "BUY" else -units))
            except (TypeError, ValueError, KeyError):
                pass
        positions[ticker] = {"shares": shares, "cost": _number(item.get("avg_price")),
                             "trades": sorted(transactions)}
    return positions


def _starting_day(period, trades):
    today = date.today()
    if period == "YTD":
        first = date(today.year, 1, 1)
    else:
        first = today - timedelta(days=PERIODS[period])
    if trades:
        first = max(first, min(trades))
    return first


def _daily_series(history, positions, start):
    # Returns normalized to 0% on the first common trading date. Historical
    # holdings are inferred only where individual transaction records exist.
    price_dates = sorted(set(history.get("SPY", {})))
    available = [d for d in price_dates if d >= start.isoformat()]
    if len(available) < 2:
        return [], [], []
    valid = [t for t in positions if t in history]
    portfolio_return, spy_return = 100.0, 100.0
    lines, benchmark = [], []
    for i, day in enumerate(available):
        if i == 0:
            lines.append({"date": day, "value": 0.0})
            benchmark.append({"date": day, "value": 0.0})
            continue
        prev = available[i-1]
        prev_spy = history["SPY"].get(prev)
        now_spy = history["SPY"].get(day)
        if prev_spy and now_spy:
            spy_return *= now_spy / prev_spy
        weighted, total = 0.0, 0.0
        prev_date = date.fromisoformat(prev)
        for ticker in valid:
            prices = history[ticker]
            if prev not in prices or day not in prices:
                continue
            p0, p1 = prices[prev], prices[day]
            trades = positions[ticker]["trades"]
            # No reconstructed history for tickers without dated transactions.
            units = sum(delta for tx_date, delta in trades if tx_date <= prev_date)
            if units <= 0:
                continue
            weight = units * p0
            total += weight
            weighted += weight * (p1 / p0 - 1)
        if total > 0:
            portfolio_return *= 1 + weighted / total
        lines.append({"date": day, "value": round((portfolio_return - 100), 3)})
        benchmark.append({"date": day, "value": round((spy_return - 100), 3)})
    return lines, benchmark, valid


def _intraday_series(history, positions):
    # Constant-current-weight intraday proxy, not an account TWR.
    common = sorted(set(history.get("SPY", {})))
    if len(common) < 2:
        return [], []
    initial = {}
    for ticker, p in positions.items():
        s = history.get(ticker, {})
        if s and p["shares"] > 0:
            first = next((s[x] for x in common if x in s), None)
            if first:
                initial[ticker] = (p["shares"] * first, first)
    base = sum(v[0] for v in initial.values())
    if base <= 0:
        return [], []
    spy0 = history["SPY"][common[0]]
    a, b = [], []
    for point in common:
        acc = 0.0
        for ticker, (weight, first) in initial.items():
            current = history[ticker].get(point)
            if current is None:
                # Do not fill a gap with a made-up daily quote.
                acc += weight
            else:
                acc += weight * current / first
        a.append({"date": point, "value": round((acc / base - 1) * 100, 3)})
        b.append({"date": point, "value": round((history["SPY"][point] / spy0 - 1) * 100, 3)})
    return a, b


def get_public_analytics(portfolio, period):
    if period not in PERIODS:
        raise ValueError("Invalid period")
    positions = _positions(portfolio)
    if not positions:
        return {"holdings": [], "sectors": [], "performance": [], "spy": [], "gainers": [], "period": period}
    # Cache excludes the raw portfolio from response. An update to the
    # portfolio changes the fingerprint, so cached allocations are invalidated.
    fingerprint = tuple(sorted((t, p["shares"], p["cost"], tuple(p["trades"]))
                               for t, p in positions.items()))
    key = (period, fingerprint)
    with _lock:
        cached = _cache.get(key)
        if cached and time.time() - cached[0] < 900:
            return cached[1]
    trades = [d for p in positions.values() for d, _ in p["trades"]]
    is_intra = period if period in ("1D", "1W") else None
    since = _starting_day(period, trades) - timedelta(days=7)
    history = _load_history(positions, since, is_intra)
    if is_intra:
        performance, spy = _intraday_series(history, positions)
        note = "Current-holdings weighted intraday price-return proxy; not actual account performance."
    else:
        perf_start = _starting_day(period, trades)
        performance, spy, _ = _daily_series(history, positions, perf_start)
        note = ("Transaction-weighted holdings price-return proxy since available trade records. "
                "Excludes cash, dividends, FX, fees and fully closed historical positions.")
    holdings, sector_totals = [], defaultdict(float)
    values = {}
    for ticker, p in positions.items():
        series = history.get(ticker, {})
        prices = [v for _, v in sorted(series.items())]
        latest = prices[-1] if prices else None
        if latest is None:
            continue
        market_value = p["shares"] * latest
        if market_value <= 0:
            continue
        values[ticker] = market_value
        sector = SECTORS.get(ticker, "Other / unclassified")
        sector_totals[sector] += market_value
        gain = (prices[-1] / prices[0] - 1) * 100 if len(prices) >= 2 else None
        holdings.append({"ticker": ticker, "sector": sector,
                         "cost_per_share": round(p["cost"], 2),
                         "current_price": round(latest, 2),
                         "period_return_pct": round(gain, 2) if gain is not None else None})
    total = sum(values.values())
    for item in holdings:
        item["allocation_pct"] = round(values[item["ticker"]] / total * 100, 2) if total else 0
    holdings.sort(key=lambda h: -h["allocation_pct"])
    sectors = [{"sector": sector, "allocation_pct": round(v / total * 100, 2)}
               for sector, v in sorted(sector_totals.items(), key=lambda x: -x[1])]
    gainers = sorted([{"ticker": h["ticker"], "return_pct": h["period_return_pct"]}
                      for h in holdings if h["period_return_pct"] is not None],
                     key=lambda x: -x["return_pct"])
    result = {"period": period, "holdings": holdings, "sectors": sectors,
              "performance": performance, "spy": spy, "gainers": gainers,
              "basis": "latest market prices", "performance_note": note,
              "available_from": performance[0]["date"] if performance else None,
              "as_of": datetime.now(timezone.utc).isoformat(),
              "missing_tickers": sorted(set(positions) - set(values))}
    with _lock:
        if len(_cache) > 30:
            _cache.clear()
        _cache[key] = (time.time(), result)
    return result
