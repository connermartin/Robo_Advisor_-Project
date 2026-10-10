"""Questionnaire definitions and input validation.

The risk-tolerance questions live in one list so they are easy to read, change,
and document. Each answer option carries a point value from 0 (most cautious)
to 4 (most risk-tolerant). The scoring formula itself is in ``risk_profile.py``.
"""

from __future__ import annotations

# Allowed ranges for the numeric inputs.
MIN_AGE, MAX_AGE = 18, 100
MIN_HORIZON, MAX_HORIZON = 1, 50
# Sanity check: age + horizon should not run past a plausible lifetime.
MAX_AGE_PLUS_HORIZON = 110
# Starting amount for the growth projection (dollars).
MIN_INVESTMENT, MAX_INVESTMENT, DEFAULT_INVESTMENT = 1_000, 10_000_000, 10_000

# Each question: a unique key, the prompt shown to the user, and a list of
# (answer label, points) pairs ordered from most cautious (0) to most tolerant (4).
QUESTIONS: list[dict] = [
    {
        "key": "drop_reaction",
        "prompt": "If your portfolio fell 20% in a few months, what would you most likely do?",
        "options": [
            ("Sell everything to avoid further losses", 0),
            ("Sell some to reduce risk", 1),
            ("Do nothing and wait", 2),
            ("Hold, and maybe buy a little more", 3),
            ("Buy significantly more while prices are low", 4),
        ],
    },
    {
        "key": "goal",
        "prompt": "What is your main goal for this money?",
        "options": [
            ("Keep it safe; avoid losses", 0),
            ("Generate steady income", 1),
            ("Balance of income and growth", 2),
            ("Mostly long-term growth", 3),
            ("Maximum growth; I accept large swings", 4),
        ],
    },
    {
        "key": "income_stability",
        "prompt": "How stable is your income (or other means to cover expenses)?",
        "options": [
            ("Very unstable / no regular income", 0),
            ("Somewhat unstable", 1),
            ("Moderately stable", 2),
            ("Stable", 3),
            ("Very stable, with an emergency fund", 4),
        ],
    },
    {
        "key": "experience",
        "prompt": "How much investing experience do you have?",
        "options": [
            ("None", 0),
            ("A little (savings accounts, CDs)", 1),
            ("Some (mutual funds / ETFs)", 2),
            ("Good (individual stocks and funds)", 3),
            ("Extensive (through several market cycles)", 4),
        ],
    },
    {
        "key": "max_loss",
        "prompt": "What is the largest one-year loss you could accept without changing your plan?",
        "options": [
            ("0% – I can't accept any loss", 0),
            ("Up to 5%", 1),
            ("Up to 15%", 2),
            ("Up to 25%", 3),
            ("More than 25%", 4),
        ],
    },
]

MAX_POINTS_PER_QUESTION = 4
MAX_TOLERANCE_POINTS = MAX_POINTS_PER_QUESTION * len(QUESTIONS)  # 20


def option_labels(question: dict) -> list[str]:
    """Return just the answer labels for a question (for UI widgets)."""
    return [label for label, _ in question["options"]]


def points_for(question_key: str, label: str) -> int:
    """Look up the points for a chosen answer label.

    Raises:
        ValueError: if the question key or the answer label is unknown.
    """
    for q in QUESTIONS:
        if q["key"] == question_key:
            for opt_label, pts in q["options"]:
                if opt_label == label:
                    return pts
            raise ValueError(f"Unknown answer '{label}' for question '{question_key}'.")
    raise ValueError(f"Unknown question '{question_key}'.")


def labels_to_points(answers: dict[str, str]) -> dict[str, int]:
    """Convert {question_key: answer_label} into {question_key: points}."""
    return {key: points_for(key, label) for key, label in answers.items()}


def _is_whole_number(value) -> bool:
    """True if value is an int (or a float with no fractional part), but not a bool."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


def validate_inputs(age, horizon, answers: dict | None) -> list[str]:
    """Check every questionnaire input and return a list of friendly error messages.

    An empty list means the inputs are valid.

    Args:
        age: investor age in years.
        horizon: investment horizon in years.
        answers: mapping of question key -> points (0–4) for every question.
    """
    errors: list[str] = []

    if age is None or not _is_whole_number(age):
        errors.append("Please enter your age as a whole number.")
    elif not MIN_AGE <= age <= MAX_AGE:
        errors.append(f"Age must be between {MIN_AGE} and {MAX_AGE}.")

    if horizon is None or not _is_whole_number(horizon):
        errors.append("Please enter your investment horizon as a whole number of years.")
    elif not MIN_HORIZON <= horizon <= MAX_HORIZON:
        errors.append(f"Investment horizon must be between {MIN_HORIZON} and {MAX_HORIZON} years.")

    # Cross-field check only when both numbers are individually valid.
    if not errors and age + horizon > MAX_AGE_PLUS_HORIZON:
        errors.append(
            f"Age + horizon is {age + horizon}, which exceeds {MAX_AGE_PLUS_HORIZON}. "
            "Please choose a shorter horizon."
        )

    answers = answers or {}
    for q in QUESTIONS:
        pts = answers.get(q["key"])
        if pts is None:
            errors.append(f"Please answer: “{q['prompt']}”")
        elif not _is_whole_number(pts) or not 0 <= pts <= MAX_POINTS_PER_QUESTION:
            errors.append(f"Invalid answer for: “{q['prompt']}”")

    return errors


def validate_investment(amount) -> list[str]:
    """Validate the starting investment used for the projection; return error messages."""
    if amount is None or isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return ["Please enter a starting investment amount."]
    if not MIN_INVESTMENT <= amount <= MAX_INVESTMENT:
        return [f"Starting investment must be between ${MIN_INVESTMENT:,} and ${MAX_INVESTMENT:,}."]
    return []
