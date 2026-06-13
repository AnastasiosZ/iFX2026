"""
Onboarding multiple-choice questionnaire.

Each option carries trait *deltas* applied on top of a neutral 0.5 baseline.
This produces a first-pass personality vector quickly and deterministically
(no LLM needed), which the interview then refines.

Deltas are summed per trait then squashed back into [0, 1] via a midpoint-
centered clamp, so a strongly-signalled trait saturates rather than overflowing.
"""

from __future__ import annotations

import random

from .traits import TRAITS, clamp01

# How many questions to show per onboarding run. We keep a larger pool below and
# sample a fresh, shuffled subset each time so the quiz isn't identical every
# session (req: questions shouldn't be the same every time).
QUIZ_QUESTION_COUNT = 8

# Each question: id, prompt, and options. Each option has a label and a dict of
# trait -> delta (positive or negative) in roughly [-0.4, 0.4].
QUESTIONS: list[dict] = [
    {
        "id": "market_drop",
        "prompt": "Your portfolio drops 20% in a week. You...",
        "options": [
            {
                "label": "Buy more — it's on sale",
                "deltas": {"risk_tolerance": 0.35, "contrarian_tendency": 0.3, "confidence": 0.25, "risk_aversion": -0.3},
            },
            {
                "label": "Hold and wait it out",
                "deltas": {"patience": 0.35, "discipline": 0.3, "impulsivity": -0.25},
            },
            {
                "label": "Sell some to limit the damage",
                "deltas": {"risk_aversion": 0.3, "impulsivity": 0.2, "risk_tolerance": -0.25},
            },
            {
                "label": "Sell everything and step back",
                "deltas": {"risk_aversion": 0.4, "impulsivity": 0.3, "risk_tolerance": -0.4, "patience": -0.3},
            },
        ],
    },
    {
        "id": "research_style",
        "prompt": "Before making an investment, you usually...",
        "options": [
            {
                "label": "Read filings, charts, and run the numbers",
                "deltas": {"analytical_depth": 0.4, "discipline": 0.25, "impulsivity": -0.2},
            },
            {
                "label": "Skim a few opinions and headlines",
                "deltas": {"analytical_depth": 0.1, "herd_mentality": 0.2},
            },
            {
                "label": "Go with a gut feeling",
                "deltas": {"impulsivity": 0.35, "confidence": 0.2, "analytical_depth": -0.3},
            },
            {
                "label": "Follow what people I trust are doing",
                "deltas": {"herd_mentality": 0.4, "analytical_depth": -0.15},
            },
        ],
    },
    {
        "id": "horizon",
        "prompt": "Your ideal time to hold an investment is...",
        "options": [
            {
                "label": "Years — I'm in no hurry",
                "deltas": {"patience": 0.4, "discipline": 0.25, "impulsivity": -0.3},
            },
            {
                "label": "Months",
                "deltas": {"patience": 0.2, "discipline": 0.1},
            },
            {
                "label": "Days to weeks",
                "deltas": {"impulsivity": 0.2, "patience": -0.15},
            },
            {
                "label": "Minutes to hours — I trade actively",
                "deltas": {"impulsivity": 0.35, "risk_tolerance": 0.25, "patience": -0.35},
            },
        ],
    },
    {
        "id": "hot_tip",
        "prompt": "A stock everyone's talking about just doubled. You...",
        "options": [
            {
                "label": "Jump in before I miss out",
                "deltas": {"herd_mentality": 0.35, "greed": 0.3, "impulsivity": 0.3, "discipline": -0.25},
            },
            {
                "label": "Get curious and research it",
                "deltas": {"analytical_depth": 0.3, "discipline": 0.15},
            },
            {
                "label": "Assume I'm too late and avoid it",
                "deltas": {"risk_aversion": 0.25, "contrarian_tendency": 0.15},
            },
            {
                "label": "Bet against the hype",
                "deltas": {"contrarian_tendency": 0.4, "herd_mentality": -0.3, "confidence": 0.2},
            },
        ],
    },
    {
        "id": "windfall",
        "prompt": "You unexpectedly receive a year's salary to invest. You...",
        "options": [
            {
                "label": "Put it all into a few high-conviction bets",
                "deltas": {"confidence": 0.35, "risk_tolerance": 0.35, "greed": 0.25, "risk_aversion": -0.3},
            },
            {
                "label": "Spread it across many things to be safe",
                "deltas": {"risk_aversion": 0.3, "discipline": 0.25, "risk_tolerance": -0.2},
            },
            {
                "label": "Keep most in cash, invest slowly",
                "deltas": {"risk_aversion": 0.35, "patience": 0.3, "impulsivity": -0.25},
            },
            {
                "label": "Chase the highest possible return, wherever it is",
                "deltas": {"greed": 0.4, "risk_tolerance": 0.3, "discipline": -0.25},
            },
        ],
    },
    {
        "id": "plan_discipline",
        "prompt": "When you set a rule like 'sell if it drops 10%', you...",
        "options": [
            {
                "label": "Always stick to it",
                "deltas": {"discipline": 0.4, "impulsivity": -0.3},
            },
            {
                "label": "Usually stick to it",
                "deltas": {"discipline": 0.2},
            },
            {
                "label": "Often talk myself out of it",
                "deltas": {"discipline": -0.25, "impulsivity": 0.2, "confidence": 0.15},
            },
            {
                "label": "Rarely make rules in the first place",
                "deltas": {"discipline": -0.35, "impulsivity": 0.3, "analytical_depth": -0.2},
            },
        ],
    },
    {
        "id": "checking_frequency",
        "prompt": "How often do you check your portfolio?",
        "options": [
            {
                "label": "Constantly — several times a day",
                "deltas": {"impulsivity": 0.3, "patience": -0.25, "confidence": 0.1},
            },
            {
                "label": "Once a day or so",
                "deltas": {"impulsivity": 0.1},
            },
            {
                "label": "A few times a month",
                "deltas": {"patience": 0.25, "discipline": 0.15},
            },
            {
                "label": "Almost never — I set and forget",
                "deltas": {"patience": 0.4, "discipline": 0.3, "impulsivity": -0.3},
            },
        ],
    },
    {
        "id": "loss_reaction",
        "prompt": "A position is down 30% but your thesis hasn't changed. You...",
        "options": [
            {
                "label": "Average down — conviction unchanged",
                "deltas": {"confidence": 0.3, "contrarian_tendency": 0.25, "risk_tolerance": 0.25},
            },
            {
                "label": "Hold, but stop adding",
                "deltas": {"discipline": 0.25, "patience": 0.2},
            },
            {
                "label": "Trim to reduce the pain",
                "deltas": {"risk_aversion": 0.25, "impulsivity": 0.15},
            },
            {
                "label": "Exit — protect what's left",
                "deltas": {"risk_aversion": 0.35, "risk_tolerance": -0.3, "impulsivity": 0.2},
            },
        ],
    },
    {
        "id": "info_source",
        "prompt": "Where do most of your investment ideas come from?",
        "options": [
            {
                "label": "My own research and models",
                "deltas": {"analytical_depth": 0.4, "contrarian_tendency": 0.2, "herd_mentality": -0.25},
            },
            {
                "label": "Trusted analysts and newsletters",
                "deltas": {"analytical_depth": 0.2, "discipline": 0.1},
            },
            {
                "label": "Social media and online communities",
                "deltas": {"herd_mentality": 0.35, "impulsivity": 0.2, "analytical_depth": -0.15},
            },
            {
                "label": "Friends, family, and word of mouth",
                "deltas": {"herd_mentality": 0.3, "analytical_depth": -0.1},
            },
        ],
    },
    {
        "id": "fomo_check",
        "prompt": "A friend brags about doubling their money in a coin you skipped. You...",
        "options": [
            {
                "label": "Stay happy for them — my plan is my plan",
                "deltas": {"discipline": 0.3, "patience": 0.2, "herd_mentality": -0.15},
            },
            {
                "label": "Feel a pang of regret, then move on",
                "deltas": {"impulsivity": 0.1},
            },
            {
                "label": "Start hunting for the next hot coin",
                "deltas": {"herd_mentality": 0.3, "greed": 0.25, "impulsivity": 0.2},
            },
            {
                "label": "Get annoyed I missed an obvious win",
                "deltas": {"greed": 0.25, "confidence": 0.15},
            },
        ],
    },
    {
        "id": "leverage",
        "prompt": "You're offered 5× leverage to amplify gains (and losses). You...",
        "options": [
            {
                "label": "Use it aggressively — fortune favours the bold",
                "deltas": {"risk_tolerance": 0.35, "greed": 0.3, "risk_aversion": -0.3, "discipline": -0.15},
            },
            {
                "label": "Use a little, very carefully",
                "deltas": {"risk_tolerance": 0.15, "discipline": 0.15},
            },
            {
                "label": "Avoid it — leverage cuts both ways",
                "deltas": {"risk_aversion": 0.3, "discipline": 0.25, "risk_tolerance": -0.2},
            },
        ],
    },
    {
        "id": "diversification",
        "prompt": "How many different things do you want to own?",
        "options": [
            {
                "label": "A focused handful I understand deeply",
                "deltas": {"analytical_depth": 0.25, "confidence": 0.25, "contrarian_tendency": 0.15},
            },
            {
                "label": "A moderate, balanced mix",
                "deltas": {"discipline": 0.2, "risk_aversion": 0.1},
            },
            {
                "label": "As broad as possible — spread the risk",
                "deltas": {"risk_aversion": 0.3, "herd_mentality": 0.15, "risk_tolerance": -0.15},
            },
        ],
    },
    {
        "id": "earnings_drop",
        "prompt": "A company you own posts great earnings, but the stock drops anyway. You...",
        "options": [
            {
                "label": "Trust my thesis and hold or add",
                "deltas": {"confidence": 0.3, "contrarian_tendency": 0.25, "patience": 0.2},
            },
            {
                "label": "Dig in to understand why before acting",
                "deltas": {"analytical_depth": 0.3, "discipline": 0.2},
            },
            {
                "label": "Take it as a warning and trim",
                "deltas": {"risk_aversion": 0.25, "impulsivity": 0.2},
            },
        ],
    },
    {
        "id": "main_goal",
        "prompt": "What's your main investing goal?",
        "options": [
            {
                "label": "Maximize growth — I can handle the swings",
                "deltas": {"risk_tolerance": 0.35, "greed": 0.25, "risk_aversion": -0.25},
            },
            {
                "label": "Steady, reliable compounding",
                "deltas": {"patience": 0.3, "discipline": 0.3, "impulsivity": -0.2},
            },
            {
                "label": "Protect what I have above all",
                "deltas": {"risk_aversion": 0.4, "risk_tolerance": -0.3, "patience": 0.15},
            },
            {
                "label": "Beat the market by being different",
                "deltas": {"contrarian_tendency": 0.35, "confidence": 0.25, "analytical_depth": 0.2},
            },
        ],
    },
]


def score_answers(answers: dict[str, int], questions: list[dict] | None = None) -> dict[str, float]:
    """
    answers: {question_id: option_index}.
    `questions` is the exact set the user was shown (e.g. an LLM-generated batch,
    each option carrying trait deltas). Falls back to the curated pool when not
    given. Returns a sanitized trait vector; missing/invalid answers are skipped.
    """
    vec = {t: 0.5 for t in TRAITS}
    by_id = {q["id"]: q for q in (questions if questions is not None else QUESTIONS)}
    for qid, opt_idx in (answers or {}).items():
        q = by_id.get(qid)
        if q is None:
            continue
        try:
            option = q["options"][int(opt_idx)]
        except (IndexError, ValueError, TypeError):
            continue
        for trait, delta in option.get("deltas", {}).items():
            if trait in vec:
                vec[trait] += delta
    return {t: clamp01(v) for t, v in vec.items()}


def random_pool(n: int = QUIZ_QUESTION_COUNT) -> list[dict]:
    """A shuffled random subset of the curated questions (full, WITH deltas).
    Used as the fallback when LLM generation is unavailable."""
    return random.sample(QUESTIONS, min(n, len(QUESTIONS)))


def to_public(questions: list[dict]) -> list[dict]:
    """Strip trait deltas — the safe shape sent to the client to render."""
    return [
        {
            "id": q["id"],
            "prompt": q["prompt"],
            "options": [{"label": o["label"]} for o in q["options"]],
        }
        for q in questions
    ]
