"""Tests for questionnaire validation, risk scoring, and model portfolios.

Expected values are worked out by hand from the documented formula:
    score = (sum of answers / 20) * 60 + horizon_points
"""

import pytest

from src.portfolios import MODEL_PORTFOLIOS, get_weights
from src.questionnaire import (
    QUESTIONS,
    labels_to_points,
    points_for,
    validate_inputs,
    validate_investment,
)
from src.risk_profile import assess_risk, horizon_points, score_to_profile, tolerance_points

KEYS = [q["key"] for q in QUESTIONS]


def answers(*pts):
    """Build {question_key: points} from positional points in question order."""
    return dict(zip(KEYS, pts))


# ---------- horizon and tolerance points ----------

@pytest.mark.parametrize(
    "years, expected",
    [(1, 0), (2, 0), (3, 10), (5, 10), (6, 20), (10, 20), (11, 30), (20, 30), (21, 40), (50, 40)],
)
def test_horizon_points_band_edges(years, expected):
    assert horizon_points(years) == expected


def test_tolerance_points_scaling():
    assert tolerance_points(answers(0, 0, 0, 0, 0)) == 0
    assert tolerance_points(answers(4, 4, 4, 4, 4)) == 60
    # 2+2+2+2+2 = 10 raw -> 10/20*60 = 30
    assert tolerance_points(answers(2, 2, 2, 2, 2)) == 30
    # 3+1+4+0+2 = 10 raw -> 30
    assert tolerance_points(answers(3, 1, 4, 0, 2)) == 30


@pytest.mark.parametrize(
    "score, profile",
    [(0, "Conservative"), (39.9, "Conservative"), (40, "Moderate"),
     (69.9, "Moderate"), (70, "Aggressive"), (100, "Aggressive")],
)
def test_score_to_profile_thresholds(score, profile):
    assert score_to_profile(score) == profile


# ---------- full assessment (hand-calculated) ----------

def test_young_long_horizon_is_aggressive():
    # raw 3+3+3+3+3 = 15 -> 45 pts; horizon 40 -> 40 pts; total 85
    r = assess_risk(25, 40, answers(3, 3, 3, 3, 3))
    assert r.score == 85
    assert r.profile == "Aggressive"
    assert not r.capped


def test_middle_case_is_moderate():
    # raw 2*5 = 10 -> 30 pts; horizon 15 -> 30 pts; total 60
    r = assess_risk(45, 15, answers(2, 2, 2, 2, 2))
    assert r.score == 60
    assert r.profile == "Moderate"


def test_cautious_short_horizon_is_conservative():
    # raw 1*5 = 5 -> 15 pts; horizon 7 -> 20 pts; total 35
    r = assess_risk(60, 7, answers(1, 1, 1, 1, 1))
    assert r.score == 35
    assert r.profile == "Conservative"


def test_short_horizon_override_caps_profile():
    # raw 20 -> 60 pts; horizon 2 -> 0 pts; total 60 = Moderate by score, but capped
    r = assess_risk(30, 2, answers(4, 4, 4, 4, 4))
    assert r.score == 60
    assert r.profile == "Conservative"
    assert r.capped
    assert any("Override" in reason for reason in r.reasons)


def test_reasons_explain_score():
    r = assess_risk(30, 10, answers(4, 0, 2, 2, 2))
    text = " ".join(r.reasons)
    assert "10 of 20 raw points" in text
    assert "20 of 40" in text


def test_assess_risk_rejects_invalid_input():
    with pytest.raises(ValueError):
        assess_risk(10, 5, answers(2, 2, 2, 2, 2))


# ---------- validation ----------

def test_validate_accepts_good_input():
    assert validate_inputs(30, 20, answers(2, 2, 2, 2, 2)) == []


@pytest.mark.parametrize(
    "age, horizon",
    [(None, 10), (17, 10), (101, 10), (30.5, 10), ("30", 10), (True, 10),
     (30, None), (30, 0), (30, 51), (30, 2.5), (90, 30)],  # last: age + horizon > 110
)
def test_validate_rejects_bad_numbers(age, horizon):
    assert validate_inputs(age, horizon, answers(2, 2, 2, 2, 2))


def test_validate_reports_missing_answers():
    errors = validate_inputs(30, 10, {KEYS[0]: 2})
    assert len(errors) == len(KEYS) - 1


def test_validate_rejects_out_of_range_answer():
    assert validate_inputs(30, 10, answers(2, 2, 2, 2, 9))


def test_points_for_unknown_label_raises():
    with pytest.raises(ValueError):
        points_for(KEYS[0], "not a real answer")


def test_labels_to_points_roundtrip():
    labels = {q["key"]: q["options"][3][0] for q in QUESTIONS}
    assert labels_to_points(labels) == {k: 3 for k in KEYS}


@pytest.mark.parametrize("amount, ok", [(10_000, True), (1_000, True), (10_000_000, True),
                                        (999, False), (20_000_000, False), (None, False), ("5000", False)])
def test_validate_investment(amount, ok):
    assert (validate_investment(amount) == []) is ok


# ---------- model portfolios ----------

@pytest.mark.parametrize("profile", list(MODEL_PORTFOLIOS))
def test_model_portfolios_sum_to_100(profile):
    assert sum(MODEL_PORTFOLIOS[profile].values()) == pytest.approx(100)


def test_get_weights_no_tilt_matches_config():
    w = get_weights("Moderate")
    assert w["VTI"] == pytest.approx(0.35)
    assert sum(w.values()) == pytest.approx(1.0)


def test_tilt_moves_weight_proportionally():
    # Moderate: equity 60 (VTI 35, VXUS 20, VNQ 5), bond 40 (BND 25, BNDX 10, SHY 5).
    # +10 tilt -> equity 70, bond 30. VTI = 35/60*70 = 40.833..., BND = 25/40*30 = 18.75
    w = get_weights("Moderate", tilt=10)
    assert w["VTI"] == pytest.approx(35 / 60 * 70 / 100)
    assert w["BND"] == pytest.approx(0.1875)
    assert sum(w.values()) == pytest.approx(1.0)


def test_tilt_never_makes_negative_weights():
    # Aggressive has only 10% in bonds; +10 tilt moves it all to stocks.
    w = get_weights("Aggressive", tilt=10)
    assert all(v >= 0 for v in w.values())
    assert w["BND"] == pytest.approx(0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_tilt_is_clipped():
    assert get_weights("Moderate", tilt=50) == get_weights("Moderate", tilt=10)


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        get_weights("YOLO")
