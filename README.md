# 📈 Marks Portfolio & Market Monitor Pipeline

An automated GitHub Actions tracking pipeline for live stock price alerts, market sentiment monitoring, and portfolio management with Discord notifications.

---

## 🛠️ Portfolio Management Guide (Marks Portfolio)

All portfolio holdings are stored inside `portfolio/portfolio.json`. 

### Adding or Updating a Position
To log a trade and automatically send an updated donut allocation chart to Discord, run the following command in your terminal:

```bash
# Command format:
python portfolio/portfolio_update.py [ACTION] [TICKER] [SHARES] [PRICE]

# Examples:
python portfolio/portfolio_update.py BUY APP 5 300.00
python portfolio/portfolio_update.py BUY AMZN 10 180.50
python portfolio/portfolio_update.py SELL META 2 525.00
