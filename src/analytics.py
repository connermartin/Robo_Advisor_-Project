"""Portfolio analytics: return, risk, Sharpe ratio, drawdown, backtest, projection.

Pure numpy/pandas — no Streamlit — so every function can be unit-tested against
small hand-calculated examples (see tests/test_analytics.py).

Conventions
-----------
* Returns are simple daily returns: r_t = P_t / P_{t-1} - 1.
* Annualization uses 252 trading days per year:
      annual mean   = mean(daily r) * 252
      annual vol    = std(daily r) * sqrt(252)     (sample std, ddof = 1)
      annual cov    = cov(daily r) * 252
* Portfolio expected return  = w · mu            (weighted average)
  Portfolio volatility       = sqrt(w' Σ w)       (accounts for correlations)
  These assume the weights are held constant (i.e. continually rebalanced).
* Sharpe ratio = (expected return - risk-free rate) / volatility.
* The historical backtest rebalances to target weights at each month end.
* Max drawdown = the worst peak-to-trough fall of the backtested value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ----------------------------------------------------------------- per-asset

def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple daily returns; the first (undefined) row is dropped."""
    return prices.pct_change().dropna(how="all")


def annualized_mean(returns: pd.DataFrame | pd.Series) -> pd.Series | float:
    """Arithmetic mean daily return x 252."""
    return returns.mean() * TRADING_DAYS


def annualized_volatility(returns: pd.DataFrame | pd.Series) -> pd.Series | float:
    """Sample standard deviation of daily returns x sqrt(252)."""
    return returns.std(ddof=1) * np.sqrt(TRADING_DAYS)


def annualized_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Sample covariance matrix of daily returns x 252."""
    return returns.cov(ddof=1) * TRADING_DAYS


# ----------------------------------------------------------------- portfolio

def align_weights(weights: dict[str, float] | pd.Series, tickers) -> np.ndarray:
    """Return weights as a numpy array in the given ticker order (missing = 0).

    Raises:
        ValueError: if the weights don't sum to 1 (within rounding) or any is negative.
    """
    w = pd.Series(weights, dtype=float).reindex(list(tickers)).fillna(0.0).to_numpy()
    if np.any(w < -1e-12):
        raise ValueError("Weights cannot be negative.")
    if not np.isclose(w.sum(), 1.0, atol=1e-6):
        raise ValueError(f"Weights must sum to 1.0 (got {w.sum():.4f}).")
    return w


def portfolio_return(weights: np.ndarray, mean_returns: np.ndarray | pd.Series) -> float:
    """Expected portfolio return: w · mu."""
    return float(np.dot(weights, np.asarray(mean_returns)))


def portfolio_volatility(weights: np.ndarray, cov: np.ndarray | pd.DataFrame) -> float:
    """Portfolio volatility: sqrt(w' Σ w)."""
    var = float(weights @ np.asarray(cov) @ weights)
    return float(np.sqrt(max(var, 0.0)))  # guard tiny negative rounding error


def sharpe_ratio(expected_return: float, volatility: float, risk_free: float) -> float:
    """(expected return - risk-free rate) / volatility; NaN if volatility is ~0."""
    if volatility is None or volatility <= 1e-12:
        return float("nan")
    return (expected_return - risk_free) / volatility


# ----------------------------------------------------------------- backtest

def backtest(
    prices: pd.DataFrame,
    weights: dict[str, float] | pd.Series,
    initial: float = 10_000.0,
    rebalance: str = "monthly",
) -> pd.Series:
    """Simulate the value of a portfolio over the price history.

    The portfolio starts at ``initial`` on the first date, invested at the
    target weights. Each day every holding grows by its own return. With
    ``rebalance="monthly"``, holdings are reset to target weights at the close
    of the last trading day of each month; with ``"none"`` it is buy-and-hold.
    No trading costs or taxes are modeled.

    Returns:
        Series of portfolio value indexed by date (first value = initial).
    """
    if rebalance not in ("monthly", "none"):
        raise ValueError("rebalance must be 'monthly' or 'none'.")
    w = align_weights(weights, prices.columns)
    rets = daily_returns(prices).to_numpy()
    dates = prices.index

    # A date is a month end if the next date is in a different month (or it's the last date).
    months = dates.to_period("M")
    month_end = np.append(months[1:] != months[:-1], True)

    holdings = initial * w
    values = [initial]
    for i, r in enumerate(rets, start=1):
        holdings = holdings * (1.0 + r)
        total = holdings.sum()
        if rebalance == "monthly" and month_end[i]:
            holdings = total * w
        values.append(total)
    return pd.Series(values, index=dates, name="Portfolio value")


def drawdown_series(values: pd.Series) -> pd.Series:
    """Percent below the running peak at each date (0 at new highs, negative otherwise)."""
    return values / values.cummax() - 1.0


def max_drawdown(values: pd.Series) -> float:
    """Worst peak-to-trough decline as a negative fraction (e.g. -0.25 = -25%)."""
    return float(drawdown_series(values).min())


def cagr(values: pd.Series) -> float:
    """Compound annual growth rate of a value series, using 252 days per year."""
    periods = len(values) - 1
    if periods <= 0 or values.iloc[0] <= 0:
        return float("nan")
    years = periods / TRADING_DAYS
    return float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0)


# ----------------------------------------------------------------- projection

def lognormal_params(mean: float, vol: float) -> tuple[float, float]:
    """Convert an arithmetic annual mean/vol to the mean/std of log(1 + R).

    Using a lognormal model keeps simulated values positive while matching the
    arithmetic mean and volatility exactly:
        sigma_log^2 = ln(1 + vol^2 / (1 + mean)^2)
        mu_log      = ln(1 + mean) - sigma_log^2 / 2
    """
    sigma2 = np.log(1.0 + vol**2 / (1.0 + mean) ** 2)
    mu_log = np.log(1.0 + mean) - sigma2 / 2.0
    return float(mu_log), float(np.sqrt(sigma2))


def monte_carlo_projection(
    initial: float,
    mean: float,
    vol: float,
    years: int,
    n_paths: int = 2000,
    percentiles: tuple[int, ...] = (10, 50, 90),
    seed: int | None = 471,
) -> pd.DataFrame:
    """Simulate many possible paths of portfolio value, year by year.

    Each year's return is drawn independently from a lognormal distribution with
    the portfolio's expected annual return and volatility (no contributions or
    withdrawals). Returns a DataFrame indexed by year 0..years with one column
    per percentile, e.g. "p10", "p50", "p90".
    """
    if years < 1:
        raise ValueError("years must be at least 1.")
    if initial <= 0:
        raise ValueError("initial investment must be positive.")
    mu_log, sigma_log = lognormal_params(mean, vol)
    rng = np.random.default_rng(seed)
    log_growth = rng.normal(mu_log, sigma_log, size=(n_paths, years))
    paths = initial * np.exp(np.cumsum(log_growth, axis=1))
    paths = np.hstack([np.full((n_paths, 1), initial), paths])

    pct = np.percentile(paths, percentiles, axis=0)
    return pd.DataFrame(
        {f"p{p}": pct[i] for i, p in enumerate(percentiles)},
        index=pd.RangeIndex(0, years + 1, name="Year"),
    )


# ----------------------------------------------------------------- summary

@dataclass
class PortfolioMetrics:
    expected_return: float
    volatility: float
    sharpe: float
    max_drawdown: float
    backtest_cagr: float
    backtest: pd.Series


def asset_statistics(prices: pd.DataFrame) -> pd.DataFrame:
    """Annualized mean return and volatility for each ETF."""
    rets = daily_returns(prices)
    return pd.DataFrame({
        "Annual Return": annualized_mean(rets),
        "Annual Volatility": annualized_volatility(rets),
    })


def portfolio_metrics(
    prices: pd.DataFrame,
    weights: dict[str, float],
    risk_free: float,
    initial: float = 10_000.0,
) -> PortfolioMetrics:
    """Compute every headline metric for one portfolio from price history."""
    rets = daily_returns(prices)
    w = align_weights(weights, prices.columns)
    exp_ret = portfolio_return(w, annualized_mean(rets))
    vol = portfolio_volatility(w, annualized_covariance(rets))
    values = backtest(prices, weights, initial=initial)
    return PortfolioMetrics(
        expected_return=exp_ret,
        volatility=vol,
        sharpe=sharpe_ratio(exp_ret, vol, risk_free),
        max_drawdown=max_drawdown(values),
        backtest_cagr=cagr(values),
        backtest=values,
    )
