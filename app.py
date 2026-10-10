"""Streamlit UI for the educational AI Robo-Advisor (FIN 471).

This file only handles layout and widgets; all logic lives in ``src/``.
Run with:  streamlit run app.py
"""

import streamlit as st

from src.portfolios import MAX_TILT, allocation_table, get_weights
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


def main() -> None:
    st.title("📈 AI Robo-Advisor & Portfolio Recommendation Tool")
    st.warning(DISCLAIMER)

    age, horizon, answer_labels, tilt = sidebar_questionnaire()
    answer_points = labels_to_points(answer_labels)

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
            st.dataframe(allocation_table(weights), hide_index=True, width="stretch")
            st.caption("Charts, expected return and risk metrics arrive in later stages.")

    with tab_compare:
        st.info("Side-by-side profile comparison will be added in stage 4.")

    with tab_assumptions:
        st.info("Assumptions and methodology will be added in stage 3.")


main()
