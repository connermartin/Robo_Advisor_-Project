"""Data fetching with timeouts, caching, and fallbacks.

Sources (all free):
  * Historical prices  – yfinance (Yahoo Finance), daily adjusted closes.
  * Risk-free rate     – FRED series DGS3MO (3-month Treasury yield), free API key.
  * Current quotes     – Finnhub ``/quote`` (free tier). No premium endpoints are used.

Fallback order for every source:
  live API  ->  last successful copy saved on disk (data/cache/)  ->  bundled default
  (data/sample_prices.csv for prices, DEFAULT_RISK_FREE_RATE for the rate,
  last historical close for quotes).

Every getter returns a ``FetchResult`` that records *where* the data came from and
any warnings, so the UI can tell the user exactly what is live and what is a fallback.
The ``get_*`` functions are wrapped in ``st.cache_data`` so the APIs are not
called on every widget change.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_PRICES_CSV = DATA_DIR / "sample_prices.csv"
SAMPLE_META_JSON = DATA_DIR / "sample_prices_meta.json"
CACHE_DIR = DATA_DIR / "cache"  # git-ignored; holds the last successful API results

LOOKBACK_YEARS = 10
MIN_HISTORY_DAYS = 252 * 3  # need at least ~3 years of overlapping data
REQUEST_TIMEOUT = 8  # seconds, for every HTTP call

# Labeled as an assumption in the UI whenever it is used.
DEFAULT_RISK_FREE_RATE = 0.04
FRED_SERIES = "DGS3MO"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"

# Source labels shown in the UI.
SRC_LIVE = "live"
SRC_DISK_CACHE = "saved copy"
SRC_SAMPLE = "sample data"
SRC_DEFAULT = "default assumption"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class FetchResult:
    """Data plus provenance: where it came from and any warnings for the user."""

    data: object
    source: str
    detail: str = ""
    warnings: list[str] = field(default_factory=list)
    synthetic: bool = False  # True when the data is randomly generated sample data


# --------------------------------------------------------------------------- keys

def get_api_key(name: str) -> str | None:
    """Return an API key from the environment / .env, or None if missing or blank."""
    value = os.getenv(name, "").strip()
    return value or None


# ---------------------------------------------------------------- disk cache I/O

def _save_prices_cache(prices: pd.DataFrame) -> None:
    """Save the last successful price download so it can be reused offline."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        prices.to_csv(CACHE_DIR / "prices.csv")
    except OSError as exc:  # read-only filesystem etc. – caching is best effort
        logger.warning("Could not write price cache: %s", exc)


def _load_prices_cache(tickers: list[str]) -> pd.DataFrame | None:
    """Load the saved price download if it exists and covers every ticker."""
    path = CACHE_DIR / "prices.csv"
    if not path.exists():
        return None
    try:
        return clean_prices(pd.read_csv(path, index_col=0, parse_dates=True), tickers)
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("Ignoring unreadable price cache: %s", exc)
        return None


def _save_json_cache(name: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / name).write_text(json.dumps(payload))
    except OSError as exc:
        logger.warning("Could not write %s: %s", name, exc)


def _load_json_cache(name: str) -> dict | None:
    path = CACHE_DIR / name
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------- prices

def clean_prices(prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Validate and tidy a price table.

    Keeps only the requested tickers, sorts by date, drops dates where any
    ticker is missing (so every ETF covers the same period), and removes
    non-positive prices.

    Raises:
        ValueError: if tickers are missing or too little history remains.
    """
    if prices is None or prices.empty:
        raise ValueError("Price data is empty.")
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        raise ValueError(f"Price data is missing tickers: {', '.join(missing)}.")

    out = prices[tickers].apply(pd.to_numeric, errors="coerce")
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.where(out > 0).dropna(how="any")

    if len(out) < MIN_HISTORY_DAYS:
        raise ValueError(
            f"Only {len(out)} days of overlapping price history; need at least {MIN_HISTORY_DAYS}."
        )
    return out


def download_prices_yfinance(tickers: list[str], years: int = LOOKBACK_YEARS) -> pd.DataFrame:
    """Download daily adjusted closes from Yahoo Finance via yfinance.

    yfinance usually returns an *empty* frame instead of raising on network
    errors, so the result is validated with ``clean_prices``.

    Raises:
        ValueError / Exception: if the download fails or is incomplete.
    """
    import yfinance as yf  # imported lazily so tests and offline runs stay fast

    raw = yf.download(
        tickers, period=f"{years}y", interval="1d", auto_adjust=True,
        progress=False, threads=False, timeout=REQUEST_TIMEOUT,
    )
    if raw is None or raw.empty:
        raise ValueError("yfinance returned no data (network issue or rate limit).")
    closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if isinstance(closes, pd.Series):  # single ticker
        closes = closes.to_frame(tickers[0])
    return clean_prices(closes, tickers)


def load_sample_prices(tickers: list[str]) -> tuple[pd.DataFrame, dict]:
    """Load the bundled sample CSV and its metadata (synthetic or real)."""
    prices = pd.read_csv(SAMPLE_PRICES_CSV, index_col=0, parse_dates=True)
    try:
        meta = json.loads(SAMPLE_META_JSON.read_text())
    except (OSError, ValueError):
        meta = {"synthetic": True, "description": "unknown origin"}
    return clean_prices(prices, tickers), meta


def fetch_price_history(tickers: list[str], years: int = LOOKBACK_YEARS) -> FetchResult:
    """Get price history: yfinance -> saved copy -> bundled sample CSV.

    Raises:
        RuntimeError: only if every source, including the bundled CSV, fails.
    """
    warnings: list[str] = []
    try:
        prices = download_prices_yfinance(tickers, years)
        _save_prices_cache(prices)
        return FetchResult(prices, SRC_LIVE, "Yahoo Finance via yfinance")
    except Exception as exc:  # noqa: BLE001 – any failure means "use a fallback"
        logger.warning("yfinance download failed: %s", exc)
        warnings.append(f"Could not download live prices from Yahoo Finance ({str(exc)[:150].rstrip('.')}).")

    cached = _load_prices_cache(tickers)
    if cached is not None:
        last = cached.index[-1].date()
        warnings.append(f"Using the last saved copy of downloaded prices (data through {last}).")
        return FetchResult(cached, SRC_DISK_CACHE, f"saved yfinance download through {last}", warnings)

    try:
        prices, meta = load_sample_prices(tickers)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "No price data available: live download failed and the sample CSV "
            f"could not be loaded ({exc})."
        ) from exc

    if meta.get("synthetic", True):
        warnings.append(
            "Using bundled SYNTHETIC sample prices (randomly generated to look realistic). "
            "Results are for demonstration only and do not reflect real ETF history."
        )
        detail = "SYNTHETIC sample data"
    else:
        warnings.append(
            f"Using bundled sample prices saved from yfinance ({meta.get('description', '')})."
        )
        detail = f"bundled yfinance snapshot ({meta.get('description', '')})"
    return FetchResult(prices, SRC_SAMPLE, detail, warnings, synthetic=meta.get("synthetic", True))


# ------------------------------------------------------------- risk-free rate

def fetch_fred_rate(api_key: str, series_id: str = FRED_SERIES) -> tuple[float, str]:
    """Return (latest annual rate as a decimal, observation date) from FRED.

    FRED reports DGS3MO in percent and uses "." for missing days, so the most
    recent numeric observation is used.

    Raises:
        requests.RequestException / ValueError: on network, HTTP, or data errors.
    """
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "sort_order": "desc", "limit": 20,
    }
    resp = requests.get(FRED_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    for obs in resp.json().get("observations", []):
        value = obs.get("value", ".")
        if value not in (".", "", None):
            return float(value) / 100.0, obs.get("date", "")
    raise ValueError(f"FRED returned no numeric observations for {series_id}.")


def fetch_risk_free_rate() -> FetchResult:
    """Get the risk-free rate: FRED -> saved copy -> labeled default assumption."""
    warnings: list[str] = []
    api_key = get_api_key("FRED_API_KEY")
    if api_key is None:
        warnings.append("FRED_API_KEY is not set, so the live Treasury rate can't be fetched.")
    else:
        try:
            rate, date = fetch_fred_rate(api_key)
            _save_json_cache("risk_free.json", {"rate": rate, "date": date})
            return FetchResult(rate, SRC_LIVE, f"FRED {FRED_SERIES} on {date}")
        except Exception as exc:  # noqa: BLE001
            # Don't echo the exception text: requests errors can include the URL with the key.
            logger.warning("FRED request failed: %s", type(exc).__name__)
            warnings.append(f"Could not reach FRED ({type(exc).__name__}).")

    cached = _load_json_cache("risk_free.json")
    if cached and isinstance(cached.get("rate"), (int, float)):
        warnings.append(f"Using the last saved FRED rate from {cached.get('date', 'unknown date')}.")
        return FetchResult(float(cached["rate"]), SRC_DISK_CACHE,
                           f"saved FRED {FRED_SERIES} from {cached.get('date')}", warnings)

    warnings.append(
        f"Using a default risk-free rate of {DEFAULT_RISK_FREE_RATE:.2%} (an assumption, not live data)."
    )
    return FetchResult(DEFAULT_RISK_FREE_RATE, SRC_DEFAULT,
                       f"{DEFAULT_RISK_FREE_RATE:.2%}, not live data", warnings)


# ------------------------------------------------------------- current quotes

def fetch_finnhub_quote(symbol: str, api_key: str, session: requests.Session | None = None) -> dict:
    """Fetch a real-time quote from Finnhub's free ``/quote`` endpoint.

    Returns a dict with price, change, change_pct, and timestamp.

    Raises:
        requests.RequestException: on network/HTTP errors (429 = rate limited).
        ValueError: if Finnhub returns an empty quote (price 0 means unknown symbol).
    """
    http = session or requests
    resp = http.get(
        FINNHUB_QUOTE_URL, params={"symbol": symbol},
        headers={"X-Finnhub-Token": api_key},  # header keeps the key out of URLs/logs
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    q = resp.json()
    if not isinstance(q, dict) or not q.get("c"):
        raise ValueError(f"Finnhub returned an empty quote for {symbol}.")
    return {
        "price": float(q["c"]),
        "change": float(q.get("d") or 0.0),
        "change_pct": float(q.get("dp") or 0.0),
        "timestamp": int(q.get("t") or 0),
    }


def fetch_quotes(tickers: list[str], last_closes: pd.Series | None = None) -> FetchResult:
    """Get current prices for each ticker: Finnhub -> last historical close.

    Stops calling Finnhub after the first connection/timeout/rate-limit error so
    an outage doesn't cost one timeout per ticker.

    Returns:
        FetchResult whose data is a DataFrame indexed by ticker with columns
        price, change_pct, source.
    """
    warnings: list[str] = []
    api_key = get_api_key("FINNHUB_API_KEY")
    rows: dict[str, dict] = {}

    if api_key is None:
        warnings.append("FINNHUB_API_KEY is not set, so live quotes are unavailable.")
    else:
        with requests.Session() as session:
            for t in tickers:
                try:
                    q = fetch_finnhub_quote(t, api_key, session)
                    rows[t] = {"price": q["price"], "change_pct": q["change_pct"], "source": "Finnhub (live)"}
                except requests.HTTPError as exc:
                    code = exc.response.status_code if exc.response is not None else "?"
                    if code == 429:
                        warnings.append("Finnhub rate limit reached (HTTP 429); try again in a minute.")
                        break
                    if code in (401, 403):
                        warnings.append(f"Finnhub rejected the request (HTTP {code}); check FINNHUB_API_KEY.")
                        break
                    warnings.append(f"Finnhub error for {t} (HTTP {code}).")
                except (requests.ConnectionError, requests.Timeout):
                    warnings.append("Could not reach Finnhub (connection error or timeout).")
                    break
                except (ValueError, requests.RequestException) as exc:
                    warnings.append(f"Finnhub quote for {t} unavailable ({type(exc).__name__}).")

    missing = [t for t in tickers if t not in rows]
    used_close, unavailable = [], []
    for t in missing:
        if last_closes is not None and t in last_closes.index:
            rows[t] = {"price": float(last_closes[t]), "change_pct": float("nan"),
                       "source": "last historical close"}
            used_close.append(t)
        else:
            rows[t] = {"price": float("nan"), "change_pct": float("nan"), "source": "n/a (no live quote)"}
            unavailable.append(t)
    if used_close:
        warnings.append(f"Showing last historical close instead of a live quote for: {', '.join(used_close)}.")
    if unavailable:
        warnings.append(f"No current price available for: {', '.join(unavailable)}.")

    table = pd.DataFrame.from_dict(rows, orient="index").reindex(tickers)
    source = SRC_LIVE if not missing else ("fallback" if len(missing) == len(tickers) else "partial")
    return FetchResult(table, source, f"{len(tickers) - len(missing)}/{len(tickers)} live", warnings)


# ------------------------------------------------------- cached entry points
# st.cache_data stores results (including fallbacks) for `ttl` seconds; the UI's
# "Refresh data" button clears it. Arguments must be hashable, hence tuples.

@st.cache_data(ttl=6 * 3600, show_spinner="Loading historical prices…")
def get_price_history(tickers: tuple[str, ...], years: int = LOOKBACK_YEARS) -> FetchResult:
    return fetch_price_history(list(tickers), years)


@st.cache_data(ttl=3600, show_spinner="Fetching risk-free rate…")
def get_risk_free_rate() -> FetchResult:
    return fetch_risk_free_rate()


@st.cache_data(ttl=300, show_spinner="Fetching current quotes…")
def get_quotes(tickers: tuple[str, ...], last_closes: pd.Series | None = None) -> FetchResult:
    return fetch_quotes(list(tickers), last_closes)


def clear_caches() -> None:
    """Clear in-memory Streamlit caches so the next run re-calls the APIs."""
    get_price_history.clear()
    get_risk_free_rate.clear()
    get_quotes.clear()

