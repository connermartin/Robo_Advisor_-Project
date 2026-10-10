"""Risk scoring: turn questionnaire answers into a 0–100 score and a profile.

Formula (documented in the README as well):

    tolerance_points = (sum of 5 answers, each 0–4) / 20 * 60      -> 0 to 60
    horizon_points   = 0  if horizon <  3 years
                       10 if  3–5 years
                       20 if  6–10 years
                       30 if 11–20 years
                       40 if  > 20 years                           -> 0 to 40
    score            = tolerance_points + horizon_points            -> 0 to 100

    Profile:  0–39 Conservative | 40–69 Moderate | 70–100 Aggressive

    Override: if horizon < 3 years the profile is capped at Conservative,
    because money needed soon should not be exposed to large stock swings.

Age is validated (and shown) but adds no points, so the time dimension is not
counted twice — the horizon already captures it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.questionnaire import MAX_TOLERANCE_POINTS, QUESTIONS, validate_inputs

TOLERANCE_WEIGHT = 60  # max points from the risk-tolerance questions
HORIZON_WEIGHT = 40    # max points from the investment horizon

# (upper bound of horizon in years, inclusive, points). Last band is open-ended.
HORIZON_BANDS: list[tuple[float, int]] = [
    (2, 0),     # under 3 years
    (5, 10),    # 3–5
    (10, 20),   # 6–10
    (20, 30),   # 11–20
    (float("inf"), 40),  # more than 20
]

SHORT_HORIZON_CAP_YEARS = 3  # horizons below this are capped at Conservative

PROFILES = ("Conservative", "Moderate", "Aggressive")
# Score thresholds: score < 40 -> Conservative, < 70 -> Moderate, else Aggressive.
MODERATE_MIN_SCORE = 40
AGGRESSIVE_MIN_SCORE = 70


@dataclass
class RiskResult:
    """Everything the UI needs to show the score and explain it."""

    score: float
    tolerance_points: float
    horizon_points: int
    profile: str
    capped: bool = False
    reasons: list[str] = field(default_factory=list)


def horizon_points(horizon_years: int) -> int:
    """Points (0–40) awarded for the investment horizon."""
    for upper, pts in HORIZON_BANDS:
        if horizon_years <= upper:
            return pts
    return HORIZON_BANDS[-1][1]  # pragma: no cover (inf band always matches)


def tolerance_points(answer_points: dict[str, int]) -> float:
    """Scale the raw answer total (0–20) to 0–60 points."""
    raw = sum(answer_points[q["key"]] for q in QUESTIONS)
    return raw / MAX_TOLERANCE_POINTS * TOLERANCE_WEIGHT


def score_to_profile(score: float) -> str:
    """Map a 0–100 score to a profile name."""
    if score >= AGGRESSIVE_MIN_SCORE:
        return "Aggressive"
    if score >= MODERATE_MIN_SCORE:
        return "Moderate"
    return "Conservative"


def assess_risk(age: int, horizon_years: int, answer_points: dict[str, int]) -> RiskResult:
    """Validate inputs, compute the score, pick the profile, and explain why.

    Args:
        age: investor age (validated, not scored).
        horizon_years: years until the money is needed.
        answer_points: {question_key: points 0–4} for every question.

    Raises:
        ValueError: with all validation messages joined, if any input is invalid.
    """
    errors = validate_inputs(age, horizon_years, answer_points)
    if errors:
        raise ValueError(" ".join(errors))

    tol = tolerance_points(answer_points)
    hor = horizon_points(horizon_years)
    score = round(tol + hor, 1)
    profile = score_to_profile(score)

    raw = sum(answer_points[q["key"]] for q in QUESTIONS)
    reasons = [
        f"Risk-tolerance answers: {raw} of {MAX_TOLERANCE_POINTS} raw points "
        f"→ {tol:.1f} of {TOLERANCE_WEIGHT} score points.",
        f"Investment horizon of {horizon_years} year(s) → {hor} of {HORIZON_WEIGHT} score points.",
        f"Total score {score:.1f} / 100 falls in the {profile} range "
        f"(0–{MODERATE_MIN_SCORE - 1} Conservative, {MODERATE_MIN_SCORE}–{AGGRESSIVE_MIN_SCORE - 1} "
        f"Moderate, {AGGRESSIVE_MIN_SCORE}–100 Aggressive).",
    ]

    capped = False
    if horizon_years < SHORT_HORIZON_CAP_YEARS and profile != "Conservative":
        capped = True
        reasons.append(
            f"Override: your horizon is under {SHORT_HORIZON_CAP_YEARS} years, so the profile is "
            f"capped at Conservative (the score alone suggested {profile})."
        )
        profile = "Conservative"

    # Highlight the strongest and weakest answers so the "why" is concrete.
    by_key = {q["key"]: q for q in QUESTIONS}
    hi_key = max(answer_points, key=answer_points.get)
    lo_key = min(answer_points, key=answer_points.get)
    if answer_points[hi_key] != answer_points[lo_key]:
        reasons.append(
            f"Most risk-tolerant answer: “{by_key[hi_key]['prompt']}” "
            f"({answer_points[hi_key]}/4). Most cautious: “{by_key[lo_key]['prompt']}” "
            f"({answer_points[lo_key]}/4)."
        )

    return RiskResult(
        score=score,
        tolerance_points=round(tol, 1),
        horizon_points=hor,
        profile=profile,
        capped=capped,
        reasons=reasons,
    )
