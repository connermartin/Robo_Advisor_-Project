"""Streamlit UI for the educational AI Robo-Advisor (FIN 471).

This file only handles layout and widgets; all logic lives in ``src/``.
Run with:  streamlit run app.py
"""

import streamlit as st

from src.data_fetch import (
    SRC_LIVE,
    SRC_SAMPLE,
    clear_caches,
    get_price_history,
    get_quotes,
    get_risk_free_rate,
)
from src.portfolios import ALL_TICKERS, MAX_TILT, allocation_table, get_weights
from src.questionnaire import (
    MAX_AGE,
    MAX_HORIZON,
    MIN_AGE,
    MIN_HORIZON,
    QUESTIONS,
    labels_to_points,
    option_labels,
    validate_inputs,
)
from src.risk_profile import assess_risk

DISCLAIMER = (
    "**Educational illustration only — not investment advice.** This tool uses hypothetical "
    "model portfolios and historical data for a class project (FIN 471). It does not know your "
    "full financial situation, and past performance does not predict future results. "
    "Consult a licensed financial professional before making investment decisions."
)

st.set_page_config(page_title="Robo-Advisor (Educational)", page_icon="📈", layout="wide")


def sidebar_questionnaire() -> tuple:
    """Render the questionnaire in the sidebar and return (age, horizon, answer_labels, tilt)."""
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
    tilt = st.sidebar.slider(
        "Tilt within profile (percentage points toward stocks)",
        min_value=-MAX_TILT, max_value=MAX_TILT, value=0, step=1,
        help="Negative = more bonds, positive = more stocks. Weight moves proportionally.",
    )
    return age, horizon, answers, tilt


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
    is_synthetic = prices is not None and prices.source == SRC_SAMPLE and "SYNTHETIC" in prices.detail
    last_closes = prices.data.iloc[-1] if prices is not None and not is_synthetic else None
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


def main() -> None:
    st.title("📈 AI Robo-Advisor & Portfolio Recommendation Tool")
    st.warning(DISCLAIMER)

    age, horizon, answer_labels, tilt = sidebar_questionnaire()
    answer_points = labels_to_points(answer_labels)
    data = load_data()
    show_data_status(data)

    tab_mine, tab_compare, tab_assumptions = st.tabs(
        ["My Portfolio", "Compare Profiles", "Assumptions & Methodology"]
    )

    with tab_mine:
        errors = validate_inputs(age, horizon, answer_points)
        if errors:
            st.info("Complete the questionnaire in the sidebar to see your profile.")
            for msg in errors:
                st.error(msg)
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
                table["Current Price ($)"] = table["Ticker"].map(q["price"]).round(2)
                table["Price Source"] = table["Ticker"].map(q["source"])
            st.dataframe(table, hide_index=True, width="stretch",
                         column_config={"Current Price ($)": st.column_config.NumberColumn(format="$%.2f")})

            if data["rf"] is not None:
                rf = data["rf"]
                st.metric("Risk-free rate (3-month T-bill)", f"{rf.data:.2%}", help=rf.detail)
                if rf.source != SRC_LIVE:
                    st.caption(f"Risk-free rate source: {rf.source} ({rf.detail}).")
            st.caption("Charts, expected return and risk metrics arrive in later stages.")

    with tab_compare:
        st.info("Side-by-side profile comparison will be added in stage 4.")

    with tab_assumptions:
        st.info("Assumptions and methodology will be added in stage 3.")


main()
