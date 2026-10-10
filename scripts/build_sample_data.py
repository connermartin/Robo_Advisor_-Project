"""Build the offline fallback price file ``data/sample_prices.csv``.

Two modes:

    python scripts/build_sample_data.py              # REAL prices from yfinance (needs internet)
    python scripts/build_sample_data.py --synthetic  # reproducible SYNTHETIC prices (no internet)

A metadata file ``data/sample_prices_meta.json`` records which mode produced the
CSV, so the app can label synthetic data clearly. Run the default (real) mode
once on your own machine before submitting so the offline fallback uses real
history.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.getLogger("streamlit").setLevel(logging.ERROR)  # silence "no runtime" cache notices

from src.data_fetch import (  # noqa: E402
    LOOKBACK_YEARS,
    SAMPLE_META_JSON,
    SAMPLE_PRICES_CSV,
    download_prices_yfinance,
)
from src.portfolios import ALL_TICKERS  # noqa: E402

# Rough long-run annual (mean return, volatility) assumptions used ONLY for the
# synthetic data, chosen to resemble each asset class. Not forecasts.
SYNTHETIC_PARAMS = {
    "VTI":  (0.10, 0.17),
    "VXUS": (0.06, 0.17),
    "VNQ":  (0.07, 0.21),
    "BND":  (0.025, 0.05),
    "BNDX": (0.025, 0.045),
    "SHY":  (0.018, 0.015),
}
# Correlation matrix in ALL_TICKERS order: VTI, VXUS, VNQ, BND, BNDX, SHY.
SYNTHETIC_CORR = np.array([
    [1.00, 0.85, 0.75, 0.10, 0.10, -0.05],
    [0.85, 1.00, 0.70, 0.10, 0.10, -0.05],
    [0.75, 0.70, 1.00, 0.20, 0.15, 0.00],
    [0.10, 0.10, 0.20, 1.00, 0.70, 0.60],
    [0.10, 0.10, 0.15, 0.70, 1.00, 0.50],
    [-0.05, -0.05, 0.00, 0.60, 0.50, 1.00],
])
SEED = 471


def build_synthetic(years: int = LOOKBACK_YEARS, seed: int = SEED) -> pd.DataFrame:
    """Simulate correlated daily prices (geometric Brownian motion), starting at $100."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(date.today())
    dates = pd.bdate_range(end=end, periods=252 * years)

    mu = np.array([SYNTHETIC_PARAMS[t][0] for t in ALL_TICKERS])
    vol = np.array([SYNTHETIC_PARAMS[t][1] for t in ALL_TICKERS])
    daily_cov = np.outer(vol, vol) * SYNTHETIC_CORR / 252
    # Log-return drift so the expected simple return is roughly mu.
    daily_drift = (mu - 0.5 * vol**2) / 252

    log_rets = rng.multivariate_normal(daily_drift, daily_cov, size=len(dates))
    # Ten years of random draws can land far from the targets (sampling noise is
    # ~5%/yr for stocks), so re-center each series to hit its target drift exactly.
    # Day-to-day volatility and correlations are left untouched.
    log_rets = log_rets - log_rets.mean(axis=0) + daily_drift
    prices = 100 * np.exp(np.cumsum(log_rets, axis=0))
    return pd.DataFrame(prices.round(4), index=dates.rename("Date"), columns=ALL_TICKERS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--synthetic", action="store_true", help="generate synthetic data instead of downloading")
    args = parser.parse_args()

    if args.synthetic:
        prices = build_synthetic()
        meta = {
            "synthetic": True,
            "description": f"synthetic GBM prices, seed {SEED}, generated {date.today()}",
        }
    else:
        try:
            prices = download_prices_yfinance(ALL_TICKERS, LOOKBACK_YEARS)
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"Download failed ({exc}). Check your internet connection, or use --synthetic.")
        prices.index.name = "Date"
        meta = {
            "synthetic": False,
            "description": f"yfinance adjusted closes {prices.index[0].date()} to {prices.index[-1].date()}",
        }

    SAMPLE_PRICES_CSV.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(SAMPLE_PRICES_CSV)
    SAMPLE_META_JSON.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {len(prices)} rows x {len(prices.columns)} tickers to {SAMPLE_PRICES_CSV}")
    print(f"Metadata: {meta}")


if __name__ == "__main__":
    main()
