"""Smoke tests for chart builders: figures build, colors stay tied to entities."""

import pandas as pd
import pytest

from src import analytics as an
from src import charts
from src.portfolios import ALL_TICKERS, get_weights


@pytest.fixture
def series():
    idx = pd.bdate_range("2024-01-01", periods=5)
    return pd.Series([10_000, 10_100, 9_900, 10_300, 10_500], index=idx, dtype=float)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_donut_omits_zero_weights_and_keeps_ticker_colors(mode):
    w = get_weights("Aggressive")  # BNDX and SHY are 0
    fig = charts.allocation_donut(w, mode)
    pie = fig.data[0]
    assert list(pie.labels) == ["VTI", "VXUS", "VNQ", "BND"]
    assert list(pie.marker.colors) == [charts.ticker_color(t, mode) for t in pie.labels]


def test_every_ticker_and_profile_has_a_color():
    for t in ALL_TICKERS:
        assert charts.ticker_color(t, "light").startswith("#")
    for p in ("Conservative", "Moderate", "Aggressive"):
        assert charts.profile_color(p, "dark").startswith("#")


def test_growth_chart_traces(series):
    fig = charts.growth_chart({"Moderate": series, "Aggressive": series * 1.1},
                              highlight={"Moderate"}, extra={"You": series})
    assert [t.name for t in fig.data] == ["Moderate", "Aggressive", "You"]
    assert fig.data[0].opacity == 1.0 and fig.data[1].opacity < 1.0


def test_scatter_and_fan_build():
    stats = pd.DataFrame({"Annual Return": [0.1, 0.03], "Annual Volatility": [0.17, 0.05]},
                         index=["VTI", "BND"])
    fig = charts.risk_return_scatter(stats, {"Moderate": (0.1, 0.06)}, risk_free=0.04, highlight="Moderate")
    assert len(fig.data) == 3  # ETFs, one portfolio, risk-free
    proj = an.monte_carlo_projection(10_000, 0.06, 0.1, years=5)
    fig = charts.projection_fan(proj, 10_000, profile="Moderate")
    assert fig.data[-1].name == "Median outcome"
