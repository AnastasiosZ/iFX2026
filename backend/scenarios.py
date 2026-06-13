"""
Scenario quizzes — the second-stage personality refinement.

After onboarding (questionnaire + AI interview) the user can play through richer,
story-driven *scenarios* at any time from a dedicated tab. Each scenario presents
a vivid situation with trade-offs; the chosen option nudges the personality
vector. Because these are deeper and more concrete than the onboarding MCQs, they
sharpen the trait estimate — and because they're replayable, the profile keeps
improving the more the user engages.

Same mechanism as questionnaire.py (trait deltas per option), but the deltas are
applied on top of the user's *current* vector rather than a neutral baseline, so
each scenario session is incremental.
"""

from __future__ import annotations

from .traits import TRAITS, clamp01

SCENARIOS: list[dict] = [
    {
        "id": "startup_equity",
        "prompt": "A startup offers you a job: take a normal salary, or half-salary "
                  "plus equity that could be worth 20× — or nothing. You...",
        "options": [
            {"label": "Take the equity bet — swing for the fences",
             "deltas": {"risk_tolerance": 0.3, "greed": 0.25, "confidence": 0.2, "risk_aversion": -0.25}},
            {"label": "Negotiate a balance of both",
             "deltas": {"analytical_depth": 0.2, "discipline": 0.2}},
            {"label": "Take the steady salary — bills are real",
             "deltas": {"risk_aversion": 0.3, "patience": 0.15, "risk_tolerance": -0.25}},
        ],
    },
    {
        "id": "crash_headline",
        "prompt": "Markets crash 35% overnight on scary headlines. Your savings are "
                  "halved on paper. The next morning you...",
        "options": [
            {"label": "Deploy your cash reserve — fear is opportunity",
             "deltas": {"contrarian_tendency": 0.35, "risk_tolerance": 0.25, "confidence": 0.2, "herd_mentality": -0.25}},
            {"label": "Do nothing and stick to the plan",
             "deltas": {"discipline": 0.35, "patience": 0.3, "impulsivity": -0.25}},
            {"label": "Raise cash until the dust settles",
             "deltas": {"risk_aversion": 0.3, "impulsivity": 0.15, "herd_mentality": 0.15}},
        ],
    },
    {
        "id": "insider_tip",
        "prompt": "A well-connected friend swears a tiny stock is about to rip. "
                  "You can't verify any of it. You...",
        "options": [
            {"label": "Throw a small bet on the tip",
             "deltas": {"herd_mentality": 0.3, "impulsivity": 0.25, "greed": 0.2, "analytical_depth": -0.15}},
            {"label": "Dig into the filings before deciding",
             "deltas": {"analytical_depth": 0.35, "discipline": 0.2, "impulsivity": -0.2}},
            {"label": "Pass — unverifiable is uninvestable",
             "deltas": {"discipline": 0.25, "contrarian_tendency": 0.2, "herd_mentality": -0.25}},
        ],
    },
    {
        "id": "winner_doubles",
        "prompt": "A position you own doubles in three weeks. The story keeps getting "
                  "louder. You...",
        "options": [
            {"label": "Let it ride — winners run",
             "deltas": {"greed": 0.3, "risk_tolerance": 0.25, "confidence": 0.2}},
            {"label": "Sell half, ride the rest risk-free",
             "deltas": {"discipline": 0.3, "analytical_depth": 0.15}},
            {"label": "Take the full profit and move on",
             "deltas": {"risk_aversion": 0.25, "patience": -0.1, "greed": -0.15}},
        ],
    },
    {
        "id": "boring_vs_exciting",
        "prompt": "Two options: a dull index fund returning ~8%/yr, or a volatile "
                  "theme you find genuinely exciting. Most of your money goes to...",
        "options": [
            {"label": "The exciting theme — I want to be involved",
             "deltas": {"risk_tolerance": 0.3, "impulsivity": 0.2, "greed": 0.15, "patience": -0.15}},
            {"label": "Split it, but tilt to the index",
             "deltas": {"discipline": 0.2, "analytical_depth": 0.15}},
            {"label": "The boring index — compounding wins",
             "deltas": {"patience": 0.35, "discipline": 0.3, "risk_aversion": 0.2, "impulsivity": -0.2}},
        ],
    },
]


def public_scenarios() -> list[dict]:
    """Scenarios without trait deltas (what the client renders)."""
    return [
        {
            "id": s["id"],
            "prompt": s["prompt"],
            "options": [{"label": o["label"]} for o in s["options"]],
        }
        for s in SCENARIOS
    ]


def apply_scenarios(current: dict[str, float], answers: dict[str, int]) -> dict[str, float]:
    """
    Apply scenario answers ON TOP of the user's current vector (incremental
    refinement). answers: {scenario_id: option_index}. Returns a clamped vector.
    """
    vec = {t: float(current.get(t, 0.5)) for t in TRAITS}
    by_id = {s["id"]: s for s in SCENARIOS}
    for sid, opt_idx in (answers or {}).items():
        s = by_id.get(sid)
        if s is None:
            continue
        try:
            option = s["options"][int(opt_idx)]
        except (IndexError, ValueError, TypeError):
            continue
        for trait, delta in option["deltas"].items():
            if trait in vec:
                vec[trait] += delta
    return {t: clamp01(v) for t, v in vec.items()}
