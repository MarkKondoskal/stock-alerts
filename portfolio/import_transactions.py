import csv
import json
import os
from datetime import datetime
from collections import defaultdict

# ----- Configuration -----
PORTFOLIO_JSON = "marks_portfolio.json"   # update path if needed
DANISH_CSV = "transactions-and-notes-export.csv"
MERRILL_CSV = "ExportData_2026-08-24_06-33-11_ET.csv"

# ----- Symbol Mapping -----
# Map the names in the CSV files to your JSON ticker symbols.
# Add any missing ones.
SYMBOL_MAP = {
    "Novo Nordisk B": "NVO",
    "Mastercard": "MA",
    "Nebius Group": "NBIS",   # you may not have this in JSON, but we'll add if found
    "ASML Holding": "ASML",
    "SoFi Technologies": "SOFI",
    "Celsius": "CELH",
    "Zeta Global A": "ZETA",
    "Vistra": "VST",
    "Meta Platforms A": "META",
    "Alphabet A": "GOOG",
    "Taiwan S Manufacturing ADR": "TSM",
    "Pagaya Technologies A": "PGY",
    "VICI PPTYS INC": "VICI",  # not in your JSON, but might appear
    "S&P Global Inc": "SPGI",
    "Chevron Corp": "CVX",     # not in JSON but may appear
    "Salesforce Inc": "CRM",
    "Microsoft Corp": "MSFT",
    "Adobe Inc": "ADBE",
    "Oracle Corp": "ORCL",
    "Applovin Corp": "APP",
    "Amazon.com Inc": "AMZN",
    "Advanced Micro Devices": "AMD",
    "Duolingo Inc": "DUOL",
    "Uber Technologies": "UBER",
    "Vanguard 500 Index Fund": "VOO",  # not in JSON
    "iShares 20+ Year Treasury Bond ETF": "TLT",  # not in JSON
    "iShares 0-3 Month Treasury Bond ETF": "SGOV",  # not in JSON
    "Schwab US Dividend Equity": "SCHD",  # not in JSON
    "Mobility Global Inc": "MBGL",  # not in JSON
    "Equifax Inc": "EFX",  # not in JSON
    "Devon Energy Corp": "DVN",  # not in JSON
    "Canadian Pacific Kansas City Ltd": "CP",  # not in JSON
    "Servicenow Inc": "NOW",  # not in JSON
    "Magnite Inc": "MGNI",  # not in JSON
    "Alibaba Group Holding": "BABA",  # not in JSON
}
# You may need to add more mappings based on your actual holdings.

# ----- Helper to parse dates -----
def parse_date(date_str):
    # For Danish CSV: format "YYYY-MM-DD"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date().isoformat()
    except ValueError:
        # For Merrill CSV: "MM/DD/YYYY"
        return datetime.strptime(date_str, "%m/%d/%Y").date().isoformat()

# ----- Parse Danish CSV -----
def parse_danish_csv(file_path):
    transactions = defaultdict(list)
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            ttype = row.get("Transaktionstype", "").strip()
            if ttype not in ("KØBT", "SOLGT"):
                continue
            raw_name = row.get("Værdipapirer", "").strip()
            if not raw_name:
                continue
            ticker = SYMBOL_MAP.get(raw_name)
            if not ticker:
                print(f"Warning: no mapping for '{raw_name}' – skipping")
                continue
            quantity = float(row["Antal"].replace(",", "."))
            price = float(row["Kurs"].replace(",", "."))
            # The price is in the currency of the security; we'll keep as is.
            # Date: use "Handelsdag" (trade date)
            date_str = row.get("Handelsdag", "").strip()
            if not date_str:
                continue
            date = parse_date(date_str)
            action = "BUY" if ttype == "KØBT" else "SELL"
            # For SELL, quantity is positive in CSV, but we treat as positive shares sold.
            transactions[ticker].append({
                "date": date,
                "action": action,
                "shares": quantity,
                "price": price,
                "fee": 0.0  # we ignore fees for simplicity
            })
    return transactions

# ----- Parse Merrill CSV -----
def parse_merrill_csv(file_path):
    transactions = defaultdict(list)
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        # Skip the first few lines (header info)
        for row in reader:
            if not row:
                continue
            if row[0].startswith("Exported on") or row[0].startswith("Selected account") or row[0].startswith("Settlement date"):
                continue
            # Now we should have data rows: Settlement date, Description, Type, Symbol/CUSIP, Quantity, Price, Amount
            if len(row) < 7:
                continue
            settlement_date = row[0].strip()
            description = row[1].strip()
            type_col = row[2].strip()
            symbol_or_cusip = row[3].strip()
            quantity_str = row[4].strip()
            price_str = row[5].strip()
            amount_str = row[6].strip()

            # Determine if it's a Buy or Sell
            if "Purchase" in description:
                action = "BUY"
            elif "Sale" in description:
                action = "SELL"
            else:
                continue

            # Extract ticker from Symbol/CUSIP or from description
            ticker = None
            # The symbol column sometimes has a CUSIP, but also the ticker in description.
            # Try to get from description: e.g., "Purchase APPLOVIN CORP COM" -> APP
            # We'll use the mapping by checking all known names.
            # A simpler approach: use the symbol column if it's a ticker (e.g., "APP", "ZETA").
            # Sometimes it's empty or CUSIP.
            if symbol_or_cusip and len(symbol_or_cusip) <= 5 and symbol_or_cusip.isalpha():
                # Might be a ticker
                ticker = symbol_or_cusip
            else:
                # Parse from description: search for known names in the description
                for name, sym in SYMBOL_MAP.items():
                    if name in description:
                        ticker = sym
                        break
            if not ticker:
                print(f"Warning: could not parse ticker from '{description}'")
                continue

            # Quantity: negative for sales in CSV? In Merrill, Quantity is negative for sales? Actually they have positive and negative? In the sample, they show "Quantity" as -0.0575 for sale? Yes, they have negative for sales. So we take absolute value.
            quantity = abs(float(quantity_str.replace(",", "")))  # remove commas
            # Price: sometimes "--" for fractional share sales? We'll skip fractional shares for simplicity (or treat as full?).
            if price_str == "--" or not price_str:
                # For fractional shares, the price is in description; we'll skip these to avoid complicating.
                print(f"Warning: skipping fractional trade for {ticker} (no price)")
                continue
            price = float(price_str.replace("$", "").replace(",", ""))

            # Date: settlement_date
            date = parse_date(settlement_date)

            transactions[ticker].append({
                "date": date,
                "action": action,
                "shares": quantity,
                "price": price,
                "fee": 0.0
            })
    return transactions

# ----- Main -----
def main():
    print("Parsing Danish CSV...")
    danish_txs = parse_danish_csv(DANISH_CSV)
    print(f"Found {sum(len(v) for v in danish_txs.values())} transactions.")
    print("Parsing Merrill CSV...")
    merrill_txs = parse_merrill_csv(MERRILL_CSV)
    print(f"Found {sum(len(v) for v in merrill_txs.values())} transactions.")

    # Merge transactions (prefer Merrill for USD symbols, Danish for DKK)
    # We'll combine: if a ticker appears in both, we'll merge and sort by date.
    all_txs = defaultdict(list)
    for ticker, tx_list in danish_txs.items():
        all_txs[ticker].extend(tx_list)
    for ticker, tx_list in merrill_txs.items():
        all_txs[ticker].extend(tx_list)

    # Sort each ticker's transactions by date
    for ticker in all_txs:
        all_txs[ticker].sort(key=lambda x: x["date"])

    # Load current portfolio JSON
    with open(PORTFOLIO_JSON, "r") as f:
        portfolio = json.load(f)

    # We'll rebuild each ticker's shares, avg_price, realized_pl, transactions from the merged list.
    new_portfolio = {}
    closed_positions = []
    for ticker, txs in all_txs.items():
        # Process in chronological order
        shares = 0
        total_cost = 0.0
        realized_pl = 0.0
        # We'll store transactions as we go
        final_txs = []
        # Keep track of each transaction (including sells) for final list
        for tx in txs:
            if tx["action"] == "BUY":
                shares += tx["shares"]
                total_cost += tx["shares"] * tx["price"]
                final_txs.append(tx)
            elif tx["action"] == "SELL":
                if shares == 0:
                    print(f"Warning: SELL without position for {ticker} on {tx['date']} – skipping")
                    continue
                # Calculate realised gain based on average cost
                avg_cost = total_cost / shares if shares > 0 else 0
                realized_gain = (tx["price"] - avg_cost) * tx["shares"]
                realized_pl += realized_gain
                shares -= tx["shares"]
                total_cost = shares * avg_cost  # remaining cost
                final_txs.append(tx)
        # After processing, if shares > 0, it's open
        if shares > 0:
            avg_price = total_cost / shares if shares > 0 else 0
            new_portfolio[ticker] = {
                "shares": shares,
                "avg_price": round(avg_price, 2),
                "transactions": final_txs,
                "realized_pl": round(realized_pl, 2)
            }
        else:
            # Closed position: archive
            # We need total cost basis (sum of all BUY costs) and total realized pl
            # We already have realized_pl from above, but we also need total_cost_basis
            # We'll compute from final_txs: sum of all BUY amounts
            total_cost_basis = sum(tx["shares"] * tx["price"] for tx in final_txs if tx["action"] == "BUY")
            closed_positions.append({
                "ticker": ticker,
                "closure_date": final_txs[-1]["date"] if final_txs else datetime.now().date().isoformat(),
                "total_cost_basis": round(total_cost_basis, 2),
                "total_realized_pl": round(realized_pl, 2),
                "transactions": final_txs,
                "final_avg_price": 0.0,  # not needed
                "final_shares": 0
            })

    # Also keep any tickers that are in the current portfolio but have no transactions in the CSVs?
    # We'll keep them as-is (or we could leave them untouched). But to be safe, we'll merge.
    # If a ticker exists in portfolio but not in all_txs, we keep its existing data (but dates are wrong – user might want to fix manually).
    # We'll print a warning.
    current_tickers = set(portfolio.keys()) - {"closed_positions"}
    for ticker in current_tickers:
        if ticker not in all_txs:
            print(f"Warning: No transaction found for {ticker} in CSVs – keeping existing data (dates may be wrong).")
            new_portfolio[ticker] = portfolio[ticker]

    # Also, if there are tickers in all_txs that are not in current portfolio, we add them (e.g., NBIS)
    for ticker in all_txs:
        if ticker not in new_portfolio and ticker not in [c["ticker"] for c in closed_positions]:
            # It might have been fully sold, but if shares >0, it would have been added above.
            # If shares ==0, it's in closed_positions.
            pass

    # Update portfolio
    portfolio["closed_positions"] = closed_positions
    # Remove old tickers and add new ones
    for ticker in list(portfolio.keys()):
        if ticker != "closed_positions":
            if ticker in new_portfolio:
                portfolio[ticker] = new_portfolio[ticker]
            else:
                # If ticker not in new_portfolio and not closed, we might want to remove it
                # But we'll keep it if it exists and we have no transactions (user might have manually added)
                pass

    # Save
    with open(PORTFOLIO_JSON, "w") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
    print("Updated marks_portfolio.json written.")

if __name__ == "__main__":
    main()
