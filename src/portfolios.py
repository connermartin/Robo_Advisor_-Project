"""Model ETF portfolios and ETF metadata.

Edit ``MODEL_PORTFOLIOS`` to change the allocations; every profile's weights
must sum to 100 (percent). ``ETF_INFO`` holds display metadata for each ticker.
These are HYPOTHETICAL, EDUCATIONAL portfolios — not investment advice.
"""

from __future__ import annotations

import pandas as pd

# Display metadata for every ETF used in any model portfolio.
# "group" is used by the tilt slider: weight moves between "equity" and "bond".
ETF_INFO: dict[str, dict[str, str]] = {
    "VTI":  {"name": "Vanguard Total Stock Market ETF", "asset_class": "US Stocks", "group": "equity"},
    "VXUS": {"name": "Vanguard Total International Stock ETF", "asset_class": "International Stocks", "group": "equity"},
    "VNQ":  {"name": "Vanguard Real Estate ETF", "asset_class": "US Real Estate (REITs)", "group": "equity"},
    "BND":  {"name": "Vanguard Total Bond Market ETF", "asset_class": "US Bonds", "group": "bond"},
    "BNDX": {"name": "Vanguard Total International Bond ETF", "asset_class": "International Bonds", "group": "bond"},
    "SHY":  {"name": "iShares 1-3 Year Treasury Bond ETF", "asset_class": "Short-Term US Treasuries", "group": "bond"},
}

# Model portfolios: profile -> {ticker: weight in percent}. Weights sum to 100.
MODEL_PORTFOLIOS: dict[str, dict[str, float]] = {
    "Conservative": {"VTI": 20, "VXUS": 10, "VNQ": 0,  "BND": 40, "BNDX": 15, "SHY": 15},
    "Moderate":     {"VTI": 35, "VXUS": 20, "VNQ": 5,  "BND": 25, "BNDX": 10, "SHY": 5},
    "Aggressive":   {"VTI": 50, "VXUS": 30, "VNQ": 10, "BND": 10, "BNDX": 0,  "SHY": 0},
}

ALL_TICKERS: list[str] = list(ETF_INFO)
MAX_TILT = 10  # percentage points the tilt slider can move


def get_weights(profile: str, tilt: float = 0.0) -> dict[str, float]:
    """Return portfolio weights as fractions (summing to 1.0) for a profile.

    Args:
        profile: "Conservative", "Moderate" or "Aggressive".
        tilt: percentage points to move from bonds to stocks (positive) or
            from stocks to bonds (negative), clipped to ±MAX_TILT. Weight is
            moved proportionally within each group, and never below zero.

    Raises:
        ValueError: if the profile is unknown.
    """
    if profile not in MODEL_PORTFOLIOS:
        raise ValueError(f"Unknown profile '{profile}'. Choose from {list(MODEL_PORTFOLIOS)}.")

    base = {t: float(w) for t, w in MODEL_PORTFOLIOS[profile].items()}
    tilt = max(-MAX_TILT, min(MAX_TILT, float(tilt)))

    equity = {t: w for t, w in base.items() if ETF_INFO[t]["group"] == "equity"}
    bond = {t: w for t, w in base.items() if ETF_INFO[t]["group"] == "bond"}
    eq_total, bd_total = sum(equity.values()), sum(bond.values())

    # The group we take weight from cannot go below zero.
    if tilt > 0:
        shift = min(tilt, bd_total)
    else:
        shift = -min(-tilt, eq_total)

    if shift != 0:
        new_eq, new_bd = eq_total + shift, bd_total - shift
        equity = _rescale(equity, new_eq)
        bond = _rescale(bond, new_bd)

    combined = {**equity, **bond}
    total = sum(combined.values())
    return {t: combined[t] / total for t in base}


def _rescale(group: dict[str, float], new_total: float) -> dict[str, float]:
    """Scale a group's weights to a new total, keeping their relative sizes.

    If the group is currently empty, the new weight is split equally.
    """
    current = sum(group.values())
    if current == 0:
        return {t: new_total / len(group) for t in group}
    return {t: w / current * new_total for t, w in group.items()}


def allocation_table(weights: dict[str, float]) -> pd.DataFrame:
    """Build the display table (ticker, name, asset class, weight %) for non-zero weights."""
    rows = [
        {
            "Ticker": t,
            "Name": ETF_INFO[t]["name"],
            "Asset Class": ETF_INFO[t]["asset_class"],
            "Weight (%)": round(w * 100, 1),
        }
        for t, w in weights.items()
        if w > 1e-9
    ]
    return pd.DataFrame(rows)
