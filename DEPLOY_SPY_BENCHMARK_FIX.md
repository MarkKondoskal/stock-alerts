# Public dashboard fix — 24 October 2026

This is a complete replacement ZIP of the **stock-alerts** website repository.

Changes:
- The clean `web/static/public.html` removes the git conflict-marker text that appeared in your deployed page near the account status.
- `web/account_public.py` now uses the **same USD SPY series** from `portfolio/performance/nordnet_all_available_provisional.csv` for both US and DK.
- The actual US portfolio return stays USD; the actual DK portfolio return stays DKK. The comparison is labelled as mixed currency for Nordnet.
- The page loads `public.js` with a fresh cache-busting query parameter.

**Deployment:** Copy everything inside `stock-alerts-main/` to the root of your GitHub `stock-alerts` repository, replacing existing files. Commit, push and redeploy Render. The private-data repository is unchanged, as it already contains the common SPY USD series.

**Important:** The USD benchmark against DKK Nordnet return is suitable as a common reference but not a currency-matched investment comparison. To evaluate Danish purchasing-power performance, SPY in DKK is more directly comparable.

If you still see `<<<<<<< HEAD` in the page, search GitHub `web/static/public.html` for `<<<<<<<` and verify Render deployed your latest commit.
