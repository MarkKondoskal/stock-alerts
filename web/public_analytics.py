"""Read-only, percentage-only portfolio analytics. No portfolio quantities leave this module.

Market-value allocations use latest available split-adjusted closing prices. Performance is a
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
        raw = yf.download(tickers, period="1d", interval="5m", auto_adjust=False,
                          progress=False, threads=True, group_by="ticker")
    elif intraday == "1W":
        raw = yf.download(tickers, period="5d", interval="60m", auto_adjust=False,
                          progress=False, threads=True, group_by="ticker")
    else:
        raw = yf.download(tickers, start=start.isoformat(),
                          end=(date.today() + timedelta(days=1)).isoformat(),
                          interval="1d", auto_adjust=False, progress=False,
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
                        ts = stamp.tz_convert("UTC").isoformat() if getattr(stamp, "tzinfo", None) else stamp.isoformat()
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
    """Mark-to-market weighted price return, with SPY on identical valid dates.

    This is an invested-holdings proxy, not account TWR. When any held
    position is missing quotes, that observation is skipped rather than
    assuming a 0% return or silently dropping the missing holding.
    """
    spy_prices = history.get("SPY", {})
    spy_dates = sorted(d for d in spy_prices if d >= start.isoformat())
    if len(spy_dates) < 2:
        return [], [], []

    def units_at(ticker, day):
        tx = positions[ticker]["trades"]
        return sum(delta for d, delta in tx if d <= day)

    eligible = []
    for day in spy_dates:
        date_obj = date.fromisoformat(day)
        active = [(ticker, units_at(ticker, date_obj)) for ticker in positions]
        active = [(ticker, units) for ticker, units in active if units > 0]
        if not active or any(day not in history.get(ticker, {}) for ticker, _ in active):
            continue
        eligible.append((day, active))

    if len(eligible) < 2:
        return [], [], []
    first_day, _ = eligible[0]
    first_spy = spy_prices[first_day]
    level = 100.0
    portfolio = [{"date": first_day, "value": 0.0}]
    benchmark = [{"date": first_day, "value": 0.0}]
    previous_day, previous_active = eligible[0]
    for day, active in eligible[1:]:
        # Only positions actually held over the preceding interval count.
        # Do not turn buys/deposits into apparent investment gains.
        weights = []
        for ticker, units in previous_active:
            # A security must have been priced at both observation dates.
            if day not in history.get(ticker, {}):
                continue
            old = history[ticker][previous_day]
            new = history[ticker][day]
            weights.append((units * old, new / old - 1))
        denominator = sum(w for w, _ in weights)
        if denominator <= 0 or len(weights) != len(previous_active):
            # No defensible return available for this interval.
            previous_day, previous_active = day, active
            continue
        level *= 1 + sum(w * r for w, r in weights) / denominator
        portfolio.append({"date": day, "value": round(level - 100, 3)})
        benchmark.append({"date": day, "value": round((spy_prices[day] / first_spy - 1) * 100, 3)})
        previous_day, previous_active = day, active
    return portfolio, benchmark, list(positions)


def get_public_snapshot(portfolio):
    """Fixed current-holdings snapshot; never depends on chart selections."""
    positions = _positions(portfolio)
    if not positions:
        return {"holdings": [], "sectors": [], "basis": "latest market value"}
    fingerprint = tuple(sorted((t, p["shares"], p["cost"]) for t, p in positions.items()))
    key = ("SNAPSHOT", fingerprint)
    with _lock:
        cached = _cache.get(key)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
    import yfinance as yf
    import pandas as pd
    tickers = sorted(positions)
    raw = yf.download(tickers, period="5d", interval="1d", auto_adjust=False,
                      progress=False, threads=True, group_by="ticker")
    prices = {}
    if raw is not None and not raw.empty:
        for ticker in tickers:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    values = (raw[ticker]["Close"] if ticker in raw.columns.get_level_values(0)
                              else raw["Close"][ticker])
                else:
                    values = raw["Close"] if len(tickers) == 1 else None
                if values is not None:
                    valid = [float(v) for v in values.dropna().tolist()
                             if math.isfinite(float(v)) and float(v) > 0]
                    if valid:
                        prices[ticker] = valid[-1]
            except (KeyError, ValueError, TypeError):
                continue
    holdings = []
    values = {}
    sectors = defaultdict(float)
    for ticker, position in positions.items():
        price = prices.get(ticker)
        sector = SECTORS.get(ticker, "Other / unclassified")
        if price is not None:
            value = position["shares"] * price
            values[ticker] = value
            sectors[sector] += value
        cost = position["cost"]
        holdings.append({
            "ticker": ticker, "sector": sector,
            "cost_per_share": round(cost, 2),
            "current_price": round(price, 2) if price is not None else None,
            "return_since_cost_pct": round((price / cost - 1) * 100, 2)
                if price is not None and cost > 0 else None,
        })
    total = sum(values.values())
    for holding in holdings:
        amount = values.get(holding["ticker"])
        holding["allocation_pct"] = round(amount / total * 100, 2) if amount is not None and total else None
    holdings.sort(key=lambda x: (x["allocation_pct"] is None, -(x["allocation_pct"] or 0)))
    result = {
        "holdings": holdings,
        "sectors": [{"sector": s, "allocation_pct": round(v / total * 100, 2)}
                    for s, v in sorted(sectors.items(), key=lambda item: -item[1])],
        "basis": "latest market value",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "missing_tickers": sorted(set(positions) - set(values)),
    }
    with _lock:
        _cache[key] = (time.time(), result)
    return result


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


def _spy_selected_period_return(period, start_day):
    """Standalone SPY total-return proxy for the requested calendar window.

    Daily closing prices are used (price return, excluding dividends). YTD anchors to the last available close
    BEFORE January 1 rather than starting at the first January close.
    This is separate from the SPY line aligned to the holdings proxy.
    """
    if period in ("1D", "1W"):
        return None
    try:
        import yfinance as yf
        import pandas as pd
        query_start = start_day - timedelta(days=12)
        raw = yf.download("SPY", start=query_start.isoformat(),
                          end=(date.today() + timedelta(days=1)).isoformat(),
                          interval="1d", auto_adjust=False, progress=False,
                          threads=False)
        if raw is None or raw.empty:
            return None
        series = raw["Close"]
        if isinstance(series, pd.DataFrame):
            series = series.iloc[:, 0]
        valid = [(d.date(), _number(value)) for d, value in series.dropna().items()]
        valid = [(d, value) for d, value in valid if value > 0]
        if len(valid) < 2:
            return None
        before = [(d, value) for d, value in valid if d < start_day]
        after = [(d, value) for d, value in valid if d >= start_day]
        if period == "YTD" and before:
            initial_day, initial_price = before[-1]
        elif after:
            initial_day, initial_price = after[0]
        else:
            return None
        final_day, final_price = valid[-1]
        if final_day <= initial_day:
            return None
        return {"return_pct": round((final_price / initial_price - 1) * 100, 2),
                "from": initial_day.isoformat(), "to": final_day.isoformat()}
    except (ValueError, TypeError, KeyError, ImportError):
        return None


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
    # Include an independently anchored SPY return for the entire selected
    # window. A YTD label must NOT silently mean 'since the portfolio import'.
    requested_start = (date(date.today().year, 1, 1) if period == "YTD" else
                       date.today() - timedelta(days=PERIODS[period]))
    # ALL is naturally constrained by actual portfolio history.
    if period == "ALL" and trades:
        requested_start = min(trades)
    spy_full_period = _spy_selected_period_return(period, requested_start)
    result = {"period": period, "holdings": holdings, "sectors": sectors,
              "spy_selected_period": spy_full_period,
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
