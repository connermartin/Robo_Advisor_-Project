"""Tests for data fetching fallbacks. All network calls are mocked, so these run offline."""

import numpy as np
import pandas as pd
import pytest
import requests

from src import data_fetch as df_mod
from src.portfolios import ALL_TICKERS


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point the disk cache at a temp dir and clear API keys for every test."""
    monkeypatch.setattr(df_mod, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)


def make_prices(days=800, tickers=("AAA", "BBB")):
    idx = pd.bdate_range("2020-01-01", periods=days)
    return pd.DataFrame({t: np.linspace(100, 120, days) + i for i, t in enumerate(tickers)}, index=idx)


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            resp = requests.Response()
            resp.status_code = self.status_code
            raise requests.HTTPError(f"HTTP {self.status_code}", response=resp)


# ------------------------------------------------------------- clean_prices

def test_clean_prices_sorts_and_drops_incomplete_rows():
    p = make_prices().iloc[::-1].copy()  # reversed order
    p.iloc[0, 0] = np.nan                # one missing value
    out = df_mod.clean_prices(p, ["AAA", "BBB"])
    assert out.index.is_monotonic_increasing
    assert len(out) == len(p) - 1
    assert not out.isna().any().any()


def test_clean_prices_rejects_missing_ticker():
    with pytest.raises(ValueError, match="missing tickers"):
        df_mod.clean_prices(make_prices(), ["AAA", "ZZZ"])


def test_clean_prices_rejects_short_history():
    with pytest.raises(ValueError, match="overlapping"):
        df_mod.clean_prices(make_prices(days=100), ["AAA", "BBB"])


def test_clean_prices_rejects_empty():
    with pytest.raises(ValueError):
        df_mod.clean_prices(pd.DataFrame(), ["AAA"])


def test_clean_prices_drops_non_positive_prices():
    p = make_prices()
    p.iloc[5, 1] = 0
    assert len(df_mod.clean_prices(p, ["AAA", "BBB"])) == len(p) - 1


# ------------------------------------------------------------- price history

def test_bundled_sample_csv_has_all_tickers():
    prices, meta = df_mod.load_sample_prices(ALL_TICKERS)
    assert list(prices.columns) == ALL_TICKERS
    assert len(prices) >= df_mod.MIN_HISTORY_DAYS
    assert "synthetic" in meta


def test_price_history_live_success_saves_cache(monkeypatch):
    good = make_prices(tickers=ALL_TICKERS)
    monkeypatch.setattr(df_mod, "download_prices_yfinance", lambda t, y: good)
    res = df_mod.fetch_price_history(ALL_TICKERS)
    assert res.source == df_mod.SRC_LIVE
    assert res.warnings == []
    assert (df_mod.CACHE_DIR / "prices.csv").exists()


def test_price_history_falls_back_to_disk_cache(monkeypatch):
    good = make_prices(tickers=ALL_TICKERS)
    monkeypatch.setattr(df_mod, "download_prices_yfinance", lambda t, y: good)
    df_mod.fetch_price_history(ALL_TICKERS)  # populates the cache

    def boom(t, y):
        raise ValueError("yfinance returned no data")

    monkeypatch.setattr(df_mod, "download_prices_yfinance", boom)
    res = df_mod.fetch_price_history(ALL_TICKERS)
    assert res.source == df_mod.SRC_DISK_CACHE
    assert len(res.data) == len(good)
    assert any("saved copy" in w for w in res.warnings)


def test_price_history_falls_back_to_sample_csv(monkeypatch):
    monkeypatch.setattr(df_mod, "download_prices_yfinance",
                        lambda t, y: (_ for _ in ()).throw(ConnectionError("offline")))
    res = df_mod.fetch_price_history(ALL_TICKERS)
    assert res.source == df_mod.SRC_SAMPLE
    assert res.synthetic  # the committed sample CSV is synthetic
    assert list(res.data.columns) == ALL_TICKERS
    assert any("Yahoo Finance" in w for w in res.warnings)


def test_price_history_raises_only_when_everything_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(df_mod, "download_prices_yfinance",
                        lambda t, y: (_ for _ in ()).throw(ConnectionError("offline")))
    monkeypatch.setattr(df_mod, "SAMPLE_PRICES_CSV", tmp_path / "missing.csv")
    with pytest.raises(RuntimeError, match="No price data"):
        df_mod.fetch_price_history(ALL_TICKERS)


# ------------------------------------------------------------- risk-free rate

def test_risk_free_default_when_key_missing():
    res = df_mod.fetch_risk_free_rate()
    assert res.data == df_mod.DEFAULT_RISK_FREE_RATE
    assert res.source == df_mod.SRC_DEFAULT
    assert any("FRED_API_KEY" in w for w in res.warnings)
    assert any("assumption" in w for w in res.warnings)


def test_risk_free_parses_latest_numeric_value(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    payload = {"observations": [
        {"date": "2026-10-09", "value": "."},      # holiday / missing
        {"date": "2026-10-08", "value": "3.87"},
    ]}
    monkeypatch.setattr(df_mod.requests, "get", lambda *a, **k: FakeResponse(payload))
    res = df_mod.fetch_risk_free_rate()
    assert res.source == df_mod.SRC_LIVE
    assert res.data == pytest.approx(0.0387)
    assert "2026-10-08" in res.detail


def test_risk_free_network_error_uses_saved_then_default(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "secret-key-123")
    monkeypatch.setattr(df_mod.requests, "get",
                        lambda *a, **k: FakeResponse({"observations": [{"date": "d", "value": "4.5"}]}))
    df_mod.fetch_risk_free_rate()  # saves 0.045 to disk

    def down(*a, **k):
        raise requests.ConnectionError("https://api...?api_key=secret-key-123")

    monkeypatch.setattr(df_mod.requests, "get", down)
    res = df_mod.fetch_risk_free_rate()
    assert res.source == df_mod.SRC_DISK_CACHE
    assert res.data == pytest.approx(0.045)
    # The API key must never leak into user-facing messages.
    assert not any("secret-key-123" in w for w in res.warnings)

    (df_mod.CACHE_DIR / "risk_free.json").unlink()
    res = df_mod.fetch_risk_free_rate()
    assert res.source == df_mod.SRC_DEFAULT


def test_risk_free_empty_observations_falls_back(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr(df_mod.requests, "get", lambda *a, **k: FakeResponse({"observations": []}))
    assert df_mod.fetch_risk_free_rate().source == df_mod.SRC_DEFAULT


# ------------------------------------------------------------- quotes

def test_finnhub_empty_quote_raises():
    class S:
        def get(self, *a, **k):
            return FakeResponse({"c": 0, "d": None, "dp": None, "t": 0})

    with pytest.raises(ValueError):
        df_mod.fetch_finnhub_quote("XXXX", "k", S())


def test_quotes_without_key_use_last_close():
    closes = pd.Series({"VTI": 300.0, "BND": 72.5})
    res = df_mod.fetch_quotes(["VTI", "BND"], closes)
    assert res.data.loc["VTI", "price"] == 300.0
    assert res.data.loc["BND", "source"] == "last historical close"
    assert any("FINNHUB_API_KEY" in w for w in res.warnings)


def test_quotes_without_key_or_closes_are_nan():
    res = df_mod.fetch_quotes(["VTI"], None)
    assert np.isnan(res.data.loc["VTI", "price"])


def test_quotes_live_success(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr(df_mod, "fetch_finnhub_quote",
                        lambda s, k, sess=None: {"price": 100.0, "change": 1.0, "change_pct": 1.0, "timestamp": 1})
    res = df_mod.fetch_quotes(["VTI", "BND"])
    assert res.source == df_mod.SRC_LIVE
    assert (res.data["source"] == "Finnhub (live)").all()
    assert res.warnings == []


def test_quotes_stop_after_rate_limit(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    calls = []

    def limited(symbol, key, sess=None):
        calls.append(symbol)
        FakeResponse(status=429).raise_for_status()

    monkeypatch.setattr(df_mod, "fetch_finnhub_quote", limited)
    res = df_mod.fetch_quotes(ALL_TICKERS, pd.Series({t: 50.0 for t in ALL_TICKERS}))
    assert len(calls) == 1  # did not hammer the API after the 429
    assert any("429" in w for w in res.warnings)
    assert (res.data["source"] == "last historical close").all()


def test_quotes_partial_failure(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "k")

    def some_fail(symbol, key, sess=None):
        if symbol == "BND":
            raise ValueError("empty")
        return {"price": 10.0, "change": 0.0, "change_pct": 0.0, "timestamp": 1}

    monkeypatch.setattr(df_mod, "fetch_finnhub_quote", some_fail)
    res = df_mod.fetch_quotes(["VTI", "BND"], pd.Series({"VTI": 1.0, "BND": 2.0}))
    assert res.source == "partial"
    assert res.data.loc["VTI", "source"] == "Finnhub (live)"
    assert res.data.loc["BND", "price"] == 2.0


def test_blank_api_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "   ")
    assert df_mod.get_api_key("FRED_API_KEY") is None
