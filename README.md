# AI Robo-Advisor & Portfolio Recommendation Tool (FIN 471)

> **Educational illustration only — not investment advice.** Hypothetical model portfolios for a class project. Past performance does not predict future results.

*Work in progress — the full README is written in stage 5.*

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # optional: add free Finnhub / FRED keys
streamlit run app.py
python -m pytest                 # run tests
```

## Offline sample data
`data/sample_prices.csv` is the fallback used when Yahoo Finance can't be reached.
The committed copy is **synthetic** (see `data/sample_prices_meta.json`). To replace it
with real prices, run this once with internet access:
```bash
python scripts/build_sample_data.py              # real yfinance prices
python scripts/build_sample_data.py --synthetic  # regenerate synthetic data
```
