"""Streamlit UI for the educational AI Robo-Advisor (FIN 471).

This file only handles layout and widgets; all logic lives in ``src/``.
Run with:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

from src import analytics as an
from src import charts
from src.data_fetch import (
    LOOKBACK_YEARS,
    SRC_LIVE,
    clear_caches,
    get_price_history,
    get_quotes,
    get_risk_free_rate,
)
from src.portfolios import (
    ALL_TICKERS,
    ETF_INFO,
    MAX_TILT,
    MODEL_PORTFOLIOS,
    allocation_table,
    get_weights,
)
from src.questionnaire import (
    DEFAULT_INVESTMENT,
    MAX_AGE,
    MAX_HORIZON,
    MAX_INVESTMENT,
    MIN_AGE,
    MIN_HORIZON,
    MIN_INVESTMENT,
    QUESTIONS,
    labels_to_points,
    option_labels,
    validate_inputs,
    validate_investment,
)
from src.risk_profile import RiskResult, assess_risk

DISCLAIMER = (
    "**Educational illustration only — not investment advice.** This tool uses hypothetical "
    "model portfolios and historical data for a class project (FIN 471). It does not know your "
    "full financial situation, and past performance does not predict future results. "
    "Consult a licensed financial professional before making investment decisions."
)

st.set_page_config(page_title="Robo-Advisor (Educational)", page_icon="📈", layout="wide")


def sidebar_questionnaire() -> tuple:
    """Render the questionnaire in the sidebar.

    Returns (age, horizon, answer_labels, tilt, investment).
    """
    st.sidebar.header("Your Profile")
    age = st.sidebar.number_input(
        "Age", min_value=MIN_AGE, max_value=MAX_AGE, value=None, step=1,
        placeholder=f"{MIN_AGE}–{MAX_AGE}",
    )
    horizon = st.sidebar.number_input(
        "Investment horizon (years)", min_value=MIN_HORIZON, max_value=MAX_HORIZON,
        value=None, step=1, placeholder=f"{MIN_HORIZON}–{MAX_HORIZON}",
        help="Years until you expect to need most of this money.",
    )

    st.sidebar.subheader("Risk tolerance")
    answers = {}
    for q in QUESTIONS:
        choice = st.sidebar.selectbox(
            q["prompt"], option_labels(q), index=None,
            placeholder="Choose an answer", key=f"q_{q['key']}",
        )
        if choice is not None:
            answers[q["key"]] = choice

    st.sidebar.subheader("Optional")
    investment = st.sidebar.number_input(
        "Starting investment ($)", min_value=MIN_INVESTMENT, max_value=MAX_INVESTMENT,
        value=DEFAULT_INVESTMENT, step=1_000, help="Used only for the growth projection.",
    )
    tilt = st.sidebar.slider(
        "Tilt within profile (percentage points toward stocks)",
        min_value=-MAX_TILT, max_value=MAX_TILT, value=0, step=1,
        help="Negative = more bonds, positive = more stocks. Weight moves proportionally.",
    )
    return age, horizon, answers, tilt, investment


def sidebar_footer() -> None:
    """Short disclaimer at the bottom of the sidebar, visible on every tab."""
    st.sidebar.divider()
    st.sidebar.caption("⚠️ Educational illustration only — not investment advice. "
                       "Hypothetical portfolios; past performance does not predict future results.")


def load_data() -> dict:
    """Load prices, risk-free rate and quotes (cached, with fallbacks).

    Returns a dict with keys prices, rf, quotes (each a FetchResult or None) and
    errors (list of messages for sources with no usable fallback).
    """
    data = {"prices": None, "rf": None, "quotes": None, "errors": []}
    try:
        data["prices"] = get_price_history(tuple(ALL_TICKERS))
    except Exception as exc:  # last-resort guard: the app must never crash
        data["errors"].append(f"Historical prices are unavailable: {exc}")

    try:
        data["rf"] = get_risk_free_rate()
    except Exception as exc:
        data["errors"].append(f"Risk-free rate is unavailable: {exc}")

    # Only fall back to historical closes as "current price" if they are real prices.
    prices = data["prices"]
    last_closes = prices.data.iloc[-1] if prices is not None and not prices.synthetic else None
    try:
        data["quotes"] = get_quotes(tuple(ALL_TICKERS), last_closes)
    except Exception as exc:
        data["errors"].append(f"Current quotes are unavailable: {exc}")
    return data


def show_data_status(data: dict) -> None:
    """Sidebar panel with each source's status, plus one combined warning in the main area."""
    st.sidebar.subheader("Data")
    if st.sidebar.button("🔄 Refresh data", help="Clear cached results and call the APIs again."):
        clear_caches()
        st.rerun()

    with st.sidebar.expander("Data sources", expanded=False):
        for label, key in [("Prices", "prices"), ("Risk-free rate", "rf"), ("Quotes", "quotes")]:
            res = data[key]
            if res is None:
                st.markdown(f"❌ **{label}:** unavailable")
            else:
                icon = "✅" if res.source == SRC_LIVE else "⚠️"
                st.markdown(f"{icon} **{label}:** {res.source} — {res.detail}")
        prices = data["prices"]
        if prices is not None:
            idx = prices.data.index
            st.caption(f"Price history: {idx[0].date()} to {idx[-1].date()} ({len(idx)} trading days)")

    for msg in data["errors"]:
        st.error(msg)
    notes = [w for key in ("prices", "rf", "quotes") if data[key] for w in data[key].warnings]
    if notes:
        st.warning("**Data notice — some live data is unavailable, so fallbacks are in use:**\n"
                   + "\n".join(f"- {n}" for n in notes))


def theme_mode() -> str:
    """'dark' or 'light', following the viewer's Streamlit theme (light if unknown)."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # older Streamlit or no browser context
        return "light"


def plot(fig) -> None:
    """Display a Plotly figure full-width with Streamlit's theme."""
    st.plotly_chart(fig, theme="streamlit", width="stretch", config={"displaylogo": False})


@st.cache_data(show_spinner=False)
def profile_metrics(prices, rf: float) -> dict:
    """Metrics for every model profile (cached: depends only on prices and rf)."""
    return {name: an.portfolio_metrics(prices, get_weights(name), rf) for name in MODEL_PORTFOLIOS}


def pct(x: float) -> str:
    """Format a fraction as a percentage, or 'n/a' for NaN."""
    return "n/a" if x is None or x != x else f"{x:.2%}"


def show_risk_return(data: dict, result: RiskResult, weights: dict, tilt: int,
                     rf: float | None, horizon: int, investment, mode: str) -> None:
    """Expected return / risk metrics, per-ETF statistics and projection summary."""
    st.subheader("Estimated return and risk (historical)")
    if data["prices"] is None:
        st.error("Return and risk can't be estimated because no price data is available.")
        return
    if rf is None:
        st.error("Risk-free rate is unavailable, so the Sharpe ratio can't be computed.")
        return

    prices = data["prices"]
    if prices.synthetic:
        st.caption("⚠️ Figures below are computed from SYNTHETIC sample prices, not real ETF history.")

    m = an.portfolio_metrics(prices.data, weights, rf)
    c = st.columns(5)
    c[0].metric("Expected return (annual)", pct(m.expected_return),
                help="Weighted average of each ETF's historical mean annual return: w · μ")
    c[1].metric("Volatility (annual)", pct(m.volatility),
                help="Portfolio standard deviation including correlations: √(w′Σw)")
    c[2].metric("Sharpe ratio", "n/a" if m.sharpe != m.sharpe else f"{m.sharpe:.2f}",
                help=f"(Expected return − risk-free rate {rf:.2%}) ÷ volatility")
    c[3].metric("Max drawdown (backtest)", pct(m.max_drawdown),
                help="Worst peak-to-trough fall of the monthly-rebalanced historical backtest")
    c[4].metric("Backtest growth rate (CAGR)", pct(m.backtest_cagr),
                help="Compound annual growth actually achieved in the backtest")
    rf_res = data["rf"]
    # "\\$" stops Streamlit's Markdown from treating text between two $ signs as LaTeX.
    st.caption(f"Risk-free rate used: {rf:.2%} ({rf_res.detail}). "
               f"\\$10,000 invested at the start of the backtest would have grown to "
               f"\\${m.backtest.iloc[-1]:,.0f} by {m.backtest.index[-1].date()}.")

    # Charts: growth of $10k for every profile, and risk vs. return.
    all_m = profile_metrics(prices.data, rf)
    tilted = tilt != 0
    you = f"Your portfolio (tilt {tilt:+d} pts)"
    plot(charts.growth_chart(
        {name: pm.backtest for name, pm in all_m.items()}, highlight={result.profile}, mode=mode,
        extra={you: m.backtest} if tilted else None,
    ))
    stats = an.asset_statistics(prices.data)
    plot(charts.risk_return_scatter(
        stats, {name: (pm.volatility, pm.expected_return) for name, pm in all_m.items()},
        risk_free=rf, highlight=result.profile, mode=mode,
        extra={"You (tilted)": (m.volatility, m.expected_return)} if tilted else None,
    ))
    st.caption("Diamonds are the three model portfolios; gray dots are the individual ETFs. "
               "Up and to the left is better (more return per unit of risk). Diversified portfolios "
               "sit to the left of a straight line between their holdings because the ETFs don't move "
               "in lockstep.")

    with st.expander("Per-ETF historical statistics"):
        stats["Weight"] = [weights.get(t, 0.0) for t in stats.index]
        stats["Sharpe"] = (stats["Annual Return"] - rf) / stats["Annual Volatility"]
        st.dataframe(
            stats, width="stretch",
            column_config={
                "Annual Return": st.column_config.NumberColumn(format="percent"),
                "Annual Volatility": st.column_config.NumberColumn(format="percent"),
                "Weight": st.column_config.NumberColumn(format="percent"),
                "Sharpe": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    st.subheader(f"Projected value of ${investment:,.0f} over {horizon} years")
    errors = validate_investment(investment)
    if errors:
        for msg in errors:
            st.error(msg)
        return
    proj = an.monte_carlo_projection(float(investment), m.expected_return, m.volatility, horizon)
    end = proj.iloc[-1]
    c = st.columns(3)
    c[0].metric("Pessimistic (10th percentile)", f"${end['p10']:,.0f}")
    c[1].metric("Median (50th percentile)", f"${end['p50']:,.0f}")
    c[2].metric("Optimistic (90th percentile)", f"${end['p90']:,.0f}")
    plot(charts.projection_fan(proj, float(investment), mode=mode, profile=result.profile))
    st.caption("Monte Carlo simulation of 2,000 paths using the portfolio's historical expected "
               "return and volatility. 80% of simulated outcomes fall between the 10th and 90th "
               "percentiles. Not a forecast or a guarantee.")

# Default investors for the comparison view: a young long-horizon saver vs. a near-retiree.
COMPARE_DEFAULTS = {
    "A": {"label": "Investor A", "age": 25, "horizon": 40, "answer_index": 3},
    "B": {"label": "Investor B", "age": 60, "horizon": 7, "answer_index": 1},
}


def compare_inputs(key: str) -> tuple:
    """Inputs for one investor in the compare view; returns (age, horizon, answer_points)."""
    d = COMPARE_DEFAULTS[key]
    st.markdown(f"#### {d['label']}")
    c1, c2 = st.columns(2)
    age = c1.number_input("Age", MIN_AGE, MAX_AGE, d["age"], 1, key=f"cmp_age_{key}")
    horizon = c2.number_input("Horizon (years)", MIN_HORIZON, MAX_HORIZON, d["horizon"], 1,
                              key=f"cmp_hz_{key}")
    with st.expander("Risk-tolerance answers", expanded=False):
        labels = {q["key"]: st.selectbox(q["prompt"], option_labels(q), index=d["answer_index"],
                                         key=f"cmp_{q['key']}_{key}")
                  for q in QUESTIONS}
    return age, horizon, labels_to_points(labels)


def show_compare(data: dict, mode: str) -> None:
    """Side-by-side comparison of two hypothetical investors."""
    st.markdown("Compare two hypothetical investors side by side. Defaults: a 25-year-old with a "
                "40-year horizon vs. a 60-year-old with a 7-year horizon. Edit either one below.")
    cols = st.columns(2)
    people = {}
    for key, col in zip(("A", "B"), cols):
        with col:
            age, horizon, pts = compare_inputs(key)
            errors = validate_inputs(age, horizon, pts)
            if errors:
                for msg in errors:
                    st.error(msg)
                continue
            people[key] = (int(age), int(horizon), assess_risk(int(age), int(horizon), pts))

    if len(people) < 2:
        st.info("Fix the inputs above to see the comparison.")
        return

    prices, rf_res = data["prices"], data["rf"]
    have_data = prices is not None and rf_res is not None
    all_m = profile_metrics(prices.data, rf_res.data) if have_data else {}

    # Summary table: one column per investor.
    rows = {}
    for key, (age, horizon, res) in people.items():
        col = {"Age": str(age), "Horizon (years)": str(horizon), "Risk score": f"{res.score:.1f}",
               "Profile": res.profile + (" (capped)" if res.capped else "")}
        w = get_weights(res.profile)
        stocks = sum(v for t, v in w.items() if ETF_INFO[t]["group"] == "equity")
        col["Stocks / bonds"] = f"{stocks:.0%} / {1 - stocks:.0%}"
        if have_data:
            pm = all_m[res.profile]
            col.update({
                "Expected return": pct(pm.expected_return), "Volatility": pct(pm.volatility),
                "Sharpe ratio": "n/a" if pm.sharpe != pm.sharpe else f"{pm.sharpe:.2f}",
                "Max drawdown": pct(pm.max_drawdown),
            })
        rows[COMPARE_DEFAULTS[key]["label"]] = col
    st.dataframe(pd.DataFrame(rows), width="stretch")

    cols = st.columns(2)
    for key, col in zip(people, cols):
        _, horizon, res = people[key]
        with col:
            plot(charts.allocation_donut(get_weights(res.profile), mode,
                                         title=f"{COMPARE_DEFAULTS[key]['label']}: {res.profile}"))

    if not have_data:
        st.error("Return and risk comparisons need price data and a risk-free rate, which are unavailable.")
        return

    profiles = {res.profile for _, _, res in people.values()}
    plot(charts.growth_chart({n: pm.backtest for n, pm in all_m.items()}, highlight=profiles, mode=mode,
                             title="Historical growth of $10,000 — both investors' profiles highlighted"))

    cols = st.columns(2)
    for key, col in zip(people, cols):
        _, horizon, res = people[key]
        pm = all_m[res.profile]
        proj = an.monte_carlo_projection(10_000.0, pm.expected_return, pm.volatility, horizon)
        with col:
            plot(charts.projection_fan(proj, 10_000.0, mode=mode, profile=res.profile,
                                       title=f"{COMPARE_DEFAULTS[key]['label']}: $10,000 over {horizon} years"))
    st.caption("Same model, same historical data: the difference comes from horizon and risk tolerance. "
               "A longer horizon gives more time to recover from drawdowns, which is why the scoring "
               "gives it weight.")


def show_assumptions(data: dict) -> None:
    """Assumptions & methodology tab."""
    prices = data["prices"]
    if prices is not None:
        idx = prices.data.index
        period = (f"{idx[0].date()} to {idx[-1].date()} ({len(idx)} trading days, "
                  f"source: {prices.source} — {prices.detail})")
    else:
        period = "unavailable"
    rf = data["rf"]
    rf_text = f"{rf.data:.2%} ({rf.source}: {rf.detail})" if rf is not None else "unavailable"

    st.markdown(f"""
### Data
- **Lookback period:** up to the last {LOOKBACK_YEARS} years of daily prices. Current data: {period}.
- **Prices:** adjusted closing prices (include dividends/distributions) from Yahoo Finance via yfinance.
  If unavailable, a saved copy or the bundled sample file is used, and the app says so.
- **Risk-free rate:** latest 3-month U.S. Treasury bill yield (FRED series DGS3MO). Current value: {rf_text}.
  If FRED is unavailable, a default of 4.00% is used and labeled as an assumption.
- **Current prices:** Finnhub real-time quotes (free tier), shown for reference only; they are not used in any calculation.

### Calculations
| Metric | Formula | Plain English |
|---|---|---|
| Daily return | r = Pₜ / Pₜ₋₁ − 1 | Percent change in price from one day to the next |
| Annual return (per ETF) | mean(daily r) × 252 | Average daily return scaled to a year (252 trading days) |
| Annual volatility (per ETF) | stdev(daily r) × √252 | How much returns typically swing around their average |
| Covariance matrix Σ | cov(daily r) × 252 | How the ETFs move together |
| Portfolio expected return | w · μ | Weighted average of the ETFs' returns |
| Portfolio volatility | √(w′Σw) | Portfolio risk; lower than the weighted average when ETFs don't move in lockstep (diversification) |
| Sharpe ratio | (Rₚ − R_f) / σₚ | Extra return earned per unit of risk taken |
| Max drawdown | min(Vₜ / max(V₀…Vₜ) − 1) | Worst fall from a previous high in the backtest |
| CAGR | (V_end / V_start)^(1/years) − 1 | Steady yearly growth rate that would give the same result |

### Assumptions
- **Annualization:** 252 trading days per year.
- **Rebalancing:** expected return and volatility assume the target weights are held constant.
  The historical backtest rebalances back to target weights at the end of every month.
- **No costs:** fund expense ratios are already reflected in ETF prices, but trading costs, taxes,
  and bid/ask spreads are ignored.
- **Projection:** 2,000 simulated paths; each year's return is drawn independently from a
  lognormal distribution with the portfolio's expected annual return and volatility.
  No additional contributions or withdrawals. Bands show the 10th, 50th, and 90th percentiles.
- **Normality:** real markets have "fat tails" — extreme losses happen more often than these models assume.

### ⚠️ Past performance does not predict future results
All figures are estimates from historical data over one specific period. Future returns,
volatility, and correlations will differ — sometimes substantially. This is an educational
illustration, not personalized investment advice.
""")


def main() -> None:
    st.title("📈 AI Robo-Advisor & Portfolio Recommendation Tool")
    st.warning(DISCLAIMER)

    age, horizon, answer_labels, tilt, investment = sidebar_questionnaire()
    answer_points = labels_to_points(answer_labels)
    data = load_data()
    show_data_status(data)
    sidebar_footer()
    mode = theme_mode()

    tab_mine, tab_compare, tab_assumptions = st.tabs(
        ["My Portfolio", "Compare Profiles", "Assumptions & Methodology"]
    )

    with tab_mine:
        errors = validate_inputs(age, horizon, answer_points)
        if errors:
            st.info("👈 Complete the questionnaire in the sidebar to see your profile. Still needed:\n"
                    + "\n".join(f"- {msg}" for msg in errors))
        else:
            result = assess_risk(int(age), int(horizon), answer_points)

            c1, c2, c3 = st.columns(3)
            c1.metric("Risk score", f"{result.score:.1f} / 100")
            c2.metric("Profile", result.profile)
            c3.metric("Score parts", f"{result.tolerance_points:.1f} + {result.horizon_points}",
                      help="Tolerance points (0–60) + horizon points (0–40)")

            st.subheader("Why this profile?")
            for reason in result.reasons:
                st.markdown(f"- {reason}")

            st.subheader(f"Hypothetical {result.profile} allocation")
            weights = get_weights(result.profile, tilt)
            table = allocation_table(weights)
            if data["quotes"] is not None:
                q = data["quotes"].data
                table["Current Price"] = [
                    "n/a" if p != p else f"${p:,.2f}" for p in table["Ticker"].map(q["price"])
                ]
                table["Price Source"] = table["Ticker"].map(q["source"])
            left, right = st.columns([3, 2])
            with left:
                st.dataframe(table, hide_index=True, width="stretch")
            with right:
                plot(charts.allocation_donut(weights, mode, title=f"{result.profile} allocation"))

            rf = data["rf"].data if data["rf"] is not None else None
            show_risk_return(data, result, weights, tilt, rf, int(horizon), investment, mode)

    with tab_compare:
        show_compare(data, mode)

    with tab_assumptions:
        show_assumptions(data)


main()
