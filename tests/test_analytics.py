"""Analytics tests, each checked against a small hand-calculated example.

The arithmetic for every expected value is written in the comments.
"""

import numpy as np
import pandas as pd
import pytest

from src import analytics as an

SQRT252 = np.sqrt(252)


# ---------------------------------------------------------------- returns

def test_daily_returns_simple():
    prices = pd.DataFrame({"A": [100.0, 110.0, 99.0]})
    # 110/100 - 1 = 0.10 ; 99/110 - 1 = -0.10
    r = an.daily_returns(prices)
    assert r["A"].tolist() == pytest.approx([0.10, -0.10])


def test_annualized_mean_and_vol():
    r = pd.Series([0.01, -0.01, 0.02, 0.0])
    # mean = 0.02/4 = 0.005 -> *252 = 1.26
    assert an.annualized_mean(r) == pytest.approx(1.26)
    # deviations: .005, -.015, .015, -.005 ; squares sum = .000025+.000225+.000225+.000025 = .0005
    # sample var = .0005/3 ; std = sqrt(.0005/3) = 0.0129099 ; *sqrt(252) = 0.204939
    assert an.annualized_volatility(r) == pytest.approx(np.sqrt(0.0005 / 3) * SQRT252)
    assert an.annualized_volatility(r) == pytest.approx(0.204939, abs=1e-6)


def test_annualized_covariance():
    r = pd.DataFrame({"A": [0.01, -0.01, 0.02, 0.0], "B": [0.02, -0.02, 0.04, 0.0]})
    # B = 2A, so cov(A,B) = 2 var(A), var(B) = 4 var(A); var(A) = .0005/3
    cov = an.annualized_covariance(r)
    var_a = 0.0005 / 3 * 252
    assert cov.loc["A", "A"] == pytest.approx(var_a)
    assert cov.loc["A", "B"] == pytest.approx(2 * var_a)
    assert cov.loc["B", "B"] == pytest.approx(4 * var_a)


# ---------------------------------------------------------------- portfolio

W = np.array([0.6, 0.4])
MU = np.array([0.10, 0.05])
# sigma_A = 0.20, sigma_B = 0.10, correlation 0.5 -> cov_AB = 0.5*0.2*0.1 = 0.01
COV = np.array([[0.04, 0.01], [0.01, 0.01]])


def test_portfolio_return():
    # 0.6*0.10 + 0.4*0.05 = 0.06 + 0.02 = 0.08
    assert an.portfolio_return(W, MU) == pytest.approx(0.08)


def test_portfolio_volatility_two_assets():
    # w'Σw = 0.36*0.04 + 2*0.6*0.4*0.01 + 0.16*0.01 = 0.0144 + 0.0048 + 0.0016 = 0.0208
    # sqrt(0.0208) = 0.144222
    assert an.portfolio_volatility(W, COV) == pytest.approx(np.sqrt(0.0208))
    assert an.portfolio_volatility(W, COV) == pytest.approx(0.144222, abs=1e-6)


def test_diversification_lowers_volatility():
    # Weighted average of vols = 0.6*0.2 + 0.4*0.1 = 0.16 > 0.1442 because correlation < 1
    assert an.portfolio_volatility(W, COV) < 0.16


def test_single_asset_portfolio_vol_equals_asset_vol():
    assert an.portfolio_volatility(np.array([1.0, 0.0]), COV) == pytest.approx(0.20)


def test_sharpe_ratio():
    # (0.08 - 0.03) / 0.144222 = 0.346688
    assert an.sharpe_ratio(0.08, np.sqrt(0.0208), 0.03) == pytest.approx(0.05 / np.sqrt(0.0208))
    assert an.sharpe_ratio(0.08, np.sqrt(0.0208), 0.03) == pytest.approx(0.346688, abs=1e-6)


def test_sharpe_ratio_zero_vol_is_nan():
    assert np.isnan(an.sharpe_ratio(0.05, 0.0, 0.03))


def test_align_weights_orders_and_fills_missing():
    w = an.align_weights({"B": 0.25, "A": 0.75}, ["A", "B", "C"])
    assert w.tolist() == [0.75, 0.25, 0.0]


@pytest.mark.parametrize("bad", [{"A": 0.5, "B": 0.4}, {"A": 1.2, "B": -0.2}])
def test_align_weights_rejects_bad_weights(bad):
    with pytest.raises(ValueError):
        an.align_weights(bad, ["A", "B"])


# ---------------------------------------------------------------- drawdown / CAGR

def test_max_drawdown():
    values = pd.Series([100.0, 120.0, 90.0, 130.0, 104.0])
    # running peak: 100, 120, 120, 130, 130
    # drawdown:     0,   0,  -0.25, 0,  -0.20  -> worst = -0.25
    assert an.drawdown_series(values).tolist() == pytest.approx([0, 0, -0.25, 0, -0.20])
    assert an.max_drawdown(values) == pytest.approx(-0.25)


def test_max_drawdown_always_rising_is_zero():
    assert an.max_drawdown(pd.Series([1.0, 2.0, 3.0])) == 0.0


def test_cagr():
    # 252 daily steps = 1 year; 100 -> 110 is +10%
    values = pd.Series(np.linspace(100, 110, 253))
    assert an.cagr(values) == pytest.approx(0.10)
    # 504 steps = 2 years; 100 -> 121 is 10%/yr
    values = pd.Series(np.linspace(100, 121, 505))
    assert an.cagr(values) == pytest.approx(0.10)


# ---------------------------------------------------------------- backtest

def _two_asset_prices():
    # Mon 29 Jan (start), Tue 30, Wed 31 (month end), Thu 1 Feb
    idx = pd.to_datetime(["2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01"])
    #  A: +100% on Jan 30, flat Jan 31, -50% on Feb 1.  B: flat throughout.
    return pd.DataFrame({"A": [10.0, 20.0, 20.0, 10.0], "B": [10.0, 10.0, 10.0, 10.0]}, index=idx)


def test_backtest_monthly_rebalance_hand_calc():
    prices = _two_asset_prices()
    v = an.backtest(prices, {"A": 0.5, "B": 0.5}, initial=100)
    # Start: A 50, B 50 = 100
    # Jan 30: A 100, B 50 = 150
    # Jan 31: unchanged = 150, month end -> rebalance to A 75, B 75
    # Feb 1:  A 37.5, B 75 = 112.5
    assert v.tolist() == pytest.approx([100, 150, 150, 112.5])


def test_backtest_buy_and_hold_hand_calc():
    prices = _two_asset_prices()
    v = an.backtest(prices, {"A": 0.5, "B": 0.5}, initial=100, rebalance="none")
    # No rebalance: Feb 1 A = 100 * 0.5 = 50, B 50 -> 100
    assert v.tolist() == pytest.approx([100, 150, 150, 100])


def test_backtest_single_asset_tracks_price():
    prices = _two_asset_prices()
    v = an.backtest(prices, {"A": 1.0}, initial=1000)
    assert v.tolist() == pytest.approx([1000, 2000, 2000, 1000])


# ---------------------------------------------------------------- projection

def test_lognormal_params_zero_vol():
    mu_log, sigma_log = an.lognormal_params(0.07, 0.0)
    assert mu_log == pytest.approx(np.log(1.07))
    assert sigma_log == pytest.approx(0.0)


def test_lognormal_params_match_arithmetic_moments():
    mu_log, s = an.lognormal_params(0.08, 0.15)
    # E[1+R] = exp(mu + s^2/2) ; Var[1+R] = (exp(s^2)-1) * exp(2mu + s^2)
    assert np.exp(mu_log + s**2 / 2) - 1 == pytest.approx(0.08)
    assert np.sqrt((np.exp(s**2) - 1) * np.exp(2 * mu_log + s**2)) == pytest.approx(0.15)


def test_monte_carlo_zero_vol_is_deterministic():
    proj = an.monte_carlo_projection(10_000, 0.05, 0.0, years=3, n_paths=50)
    # Every path: 10,000 * 1.05^t
    expected = [10_000 * 1.05**t for t in range(4)]
    for col in ("p10", "p50", "p90"):
        assert proj[col].tolist() == pytest.approx(expected)


def test_monte_carlo_shape_order_and_reproducibility():
    a = an.monte_carlo_projection(10_000, 0.07, 0.15, years=20)
    b = an.monte_carlo_projection(10_000, 0.07, 0.15, years=20)
    assert list(a.index) == list(range(21))
    assert a.iloc[0].tolist() == [10_000] * 3
    assert (a["p10"] <= a["p50"]).all() and (a["p50"] <= a["p90"]).all()
    pd.testing.assert_frame_equal(a, b)  # same seed -> same result


def test_monte_carlo_median_close_to_theory():
    # Median of a lognormal after T years = initial * exp(mu_log * T)
    mu_log, _ = an.lognormal_params(0.07, 0.15)
    proj = an.monte_carlo_projection(10_000, 0.07, 0.15, years=10, n_paths=20_000)
    assert proj.loc[10, "p50"] == pytest.approx(10_000 * np.exp(mu_log * 10), rel=0.03)


@pytest.mark.parametrize("kwargs", [{"years": 0}, {"initial": 0}])
def test_monte_carlo_rejects_bad_input(kwargs):
    args = {"initial": 1000, "mean": 0.05, "vol": 0.1, "years": 5} | kwargs
    with pytest.raises(ValueError):
        an.monte_carlo_projection(**args)


# ---------------------------------------------------------------- summary

def test_portfolio_metrics_consistent_with_parts():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=300)
    prices = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=(300, 2)), axis=0)),
        index=idx, columns=["A", "B"],
    )
    w = {"A": 0.7, "B": 0.3}
    m = an.portfolio_metrics(prices, w, risk_free=0.02)
    rets = an.daily_returns(prices)
    wv = np.array([0.7, 0.3])
    assert m.expected_return == pytest.approx(wv @ (rets.mean() * 252))
    assert m.volatility == pytest.approx(np.sqrt(wv @ (rets.cov() * 252).to_numpy() @ wv))
    assert m.sharpe == pytest.approx((m.expected_return - 0.02) / m.volatility)
    assert m.max_drawdown <= 0
    assert m.backtest.iloc[0] == 10_000
