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

import random

from .traits import TRAITS, clamp01

# There are 20 predefined scenarios below; each visit to the Quizzes tab shows a
# fresh, randomly-chosen handful so it's different every time.
SCENARIO_COUNT = 5

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
    {
        "id": "liquidation_cascade",
        "prompt": "A position gaps down hard overnight and blows through the stop-loss "
                  "you set. By morning it's already past your exit. You...",
        "options": [
            {"label": "Sell immediately at market — the rule is the rule",
             "deltas": {"discipline": 0.35, "risk_aversion": 0.2, "impulsivity": 0.1}},
            {"label": "Reassess the thesis before doing anything",
             "deltas": {"analytical_depth": 0.3, "patience": 0.2, "confidence": 0.15}},
            {"label": "Hold and hope it comes back",
             "deltas": {"risk_tolerance": 0.2, "discipline": -0.25, "impulsivity": 0.15}},
        ],
    },
    {
        "id": "concentrated_bet",
        "prompt": "After months of research you're convinced one idea is a generational "
                  "winner. How much of your portfolio goes in?",
        "options": [
            {"label": "A huge chunk — conviction should be sized up",
             "deltas": {"confidence": 0.35, "risk_tolerance": 0.3, "greed": 0.2, "contrarian_tendency": 0.2}},
            {"label": "A meaningful but capped position",
             "deltas": {"discipline": 0.3, "analytical_depth": 0.2}},
            {"label": "A small starter — even great ideas can be wrong",
             "deltas": {"risk_aversion": 0.25, "discipline": 0.2, "patience": 0.15}},
        ],
    },
    {
        "id": "everyone_selling",
        "prompt": "Your whole feed is screaming that a sector is dead and dumping it. "
                  "Your own numbers say it's cheap. You...",
        "options": [
            {"label": "Buy what they're selling",
             "deltas": {"contrarian_tendency": 0.4, "confidence": 0.25, "herd_mentality": -0.3}},
            {"label": "Wait for the panic to peak, then nibble",
             "deltas": {"patience": 0.3, "discipline": 0.25, "analytical_depth": 0.15}},
            {"label": "Step aside — don't fight the tape",
             "deltas": {"herd_mentality": 0.3, "risk_aversion": 0.2}},
        ],
    },
    {
        "id": "inheritance_windfall",
        "prompt": "You inherit a large lump sum with no strings attached. You...",
        "options": [
            {"label": "Invest it all at once and stay the course",
             "deltas": {"discipline": 0.3, "confidence": 0.2, "risk_tolerance": 0.15}},
            {"label": "Drip it in slowly over many months",
             "deltas": {"patience": 0.3, "discipline": 0.25, "impulsivity": -0.2}},
            {"label": "Park most in cash until I'm sure",
             "deltas": {"risk_aversion": 0.35, "patience": 0.15, "risk_tolerance": -0.2}},
        ],
    },
    {
        "id": "friend_pitch",
        "prompt": "A close friend asks you to back their unproven business idea. You...",
        "options": [
            {"label": "Back them big — I believe in them",
             "deltas": {"herd_mentality": 0.2, "confidence": 0.2, "greed": 0.15, "analytical_depth": -0.15}},
            {"label": "Chip in a small, losable amount",
             "deltas": {"discipline": 0.2, "risk_aversion": 0.1}},
            {"label": "Ask for a plan and real numbers first",
             "deltas": {"analytical_depth": 0.35, "discipline": 0.2}},
        ],
    },
    {
        "id": "sector_rotation",
        "prompt": "Your winning sector falls out of favour while another one heats up. You...",
        "options": [
            {"label": "Rotate into the new hot sector",
             "deltas": {"herd_mentality": 0.3, "impulsivity": 0.25, "patience": -0.15}},
            {"label": "Rebalance methodically back to targets",
             "deltas": {"discipline": 0.3, "analytical_depth": 0.2}},
            {"label": "Stay put — I picked these for a reason",
             "deltas": {"patience": 0.3, "confidence": 0.25, "contrarian_tendency": 0.15}},
        ],
    },
    {
        "id": "stop_loss_rule",
        "prompt": "You're opening a new trade. Do you set a stop-loss?",
        "options": [
            {"label": "Always — before I even enter",
             "deltas": {"discipline": 0.4, "risk_aversion": 0.15, "impulsivity": -0.2}},
            {"label": "Sometimes — it depends on the trade",
             "deltas": {"discipline": 0.1}},
            {"label": "No — stops just shake me out",
             "deltas": {"risk_tolerance": 0.25, "discipline": -0.25, "confidence": 0.2}},
        ],
    },
    {
        "id": "drawdown_tolerance",
        "prompt": "How big a paper loss can you stomach before it affects your sleep?",
        "options": [
            {"label": "50%+ — I think in decades",
             "deltas": {"risk_tolerance": 0.35, "patience": 0.3, "risk_aversion": -0.25}},
            {"label": "Around 20%",
             "deltas": {"risk_tolerance": 0.1}},
            {"label": "Even 10% keeps me up at night",
             "deltas": {"risk_aversion": 0.35, "impulsivity": 0.15, "risk_tolerance": -0.25}},
        ],
    },
    {
        "id": "ipo_hype",
        "prompt": "A buzzy company is about to IPO and everyone wants in. You...",
        "options": [
            {"label": "Buy on day one",
             "deltas": {"herd_mentality": 0.3, "impulsivity": 0.25, "greed": 0.2}},
            {"label": "Wait months for the hype to cool",
             "deltas": {"patience": 0.3, "discipline": 0.25, "contrarian_tendency": 0.2}},
            {"label": "Skip it — I don't chase IPOs",
             "deltas": {"risk_aversion": 0.2, "contrarian_tendency": 0.2, "herd_mentality": -0.2}},
        ],
    },
    {
        "id": "dividend_vs_growth",
        "prompt": "Pick the style that fits you best:",
        "options": [
            {"label": "Steady dividends I can rely on",
             "deltas": {"risk_aversion": 0.25, "patience": 0.3, "discipline": 0.2}},
            {"label": "A balance of income and growth",
             "deltas": {"discipline": 0.2, "analytical_depth": 0.1}},
            {"label": "All-out growth — reinvest everything",
             "deltas": {"risk_tolerance": 0.3, "greed": 0.2, "risk_aversion": -0.2}},
        ],
    },
    {
        "id": "analyst_downgrade",
        "prompt": "A respected analyst downgrades a stock you researched and love. You...",
        "options": [
            {"label": "Trust my own work and hold",
             "deltas": {"confidence": 0.3, "contrarian_tendency": 0.25, "herd_mentality": -0.2}},
            {"label": "Re-check my thesis carefully",
             "deltas": {"analytical_depth": 0.35, "discipline": 0.2}},
            {"label": "Defer to the expert and sell",
             "deltas": {"herd_mentality": 0.3, "confidence": -0.15, "analytical_depth": -0.1}},
        ],
    },
    {
        "id": "margin_offer",
        "prompt": "Your broker offers cheap margin to boost your buying power. You...",
        "options": [
            {"label": "Lever up — amplify the gains",
             "deltas": {"risk_tolerance": 0.35, "greed": 0.3, "risk_aversion": -0.25, "discipline": -0.15}},
            {"label": "Use a modest amount with care",
             "deltas": {"risk_tolerance": 0.15, "discipline": 0.15}},
            {"label": "Decline — debt and markets don't mix for me",
             "deltas": {"risk_aversion": 0.3, "discipline": 0.25}},
        ],
    },
    {
        "id": "all_time_high",
        "prompt": "The market is at an all-time high. New money you have to invest goes...",
        "options": [
            {"label": "In now — time in beats timing",
             "deltas": {"discipline": 0.3, "patience": 0.25, "confidence": 0.15}},
            {"label": "Half now, half if it dips",
             "deltas": {"discipline": 0.2, "analytical_depth": 0.1}},
            {"label": "On the sidelines, waiting for a pullback",
             "deltas": {"risk_aversion": 0.25, "patience": 0.15, "impulsivity": 0.1}},
        ],
    },
    {
        "id": "meme_mania",
        "prompt": "A meme stock is rocketing on social media. You...",
        "options": [
            {"label": "Ride the wave with a fun-money bet",
             "deltas": {"herd_mentality": 0.3, "impulsivity": 0.3, "greed": 0.25, "discipline": -0.2}},
            {"label": "Watch from the sidelines, fascinated",
             "deltas": {"discipline": 0.2, "patience": 0.15}},
            {"label": "Think about shorting the madness",
             "deltas": {"contrarian_tendency": 0.4, "confidence": 0.25, "risk_tolerance": 0.2, "herd_mentality": -0.3}},
        ],
    },
    {
        "id": "retirement_horizon",
        "prompt": "Your investing timeline is...",
        "options": [
            {"label": "30+ years — I'm playing the long game",
             "deltas": {"patience": 0.4, "discipline": 0.25, "risk_tolerance": 0.2}},
            {"label": "About 10 years",
             "deltas": {"patience": 0.2, "discipline": 0.1}},
            {"label": "A few years — I'll need it soon",
             "deltas": {"risk_aversion": 0.3, "patience": -0.15, "risk_tolerance": -0.2}},
        ],
    },
]


def random_pool(n: int = SCENARIO_COUNT) -> list[dict]:
    """A shuffled random subset of the curated scenarios (full, WITH deltas).
    Used as the fallback when LLM generation is unavailable."""
    return random.sample(SCENARIOS, min(n, len(SCENARIOS)))


def to_public(scenarios: list[dict]) -> list[dict]:
    """Strip trait deltas — the safe shape sent to the client to render."""
    return [
        {
            "id": s["id"],
            "prompt": s["prompt"],
            "options": [{"label": o["label"]} for o in s["options"]],
        }
        for s in scenarios
    ]


def apply_scenarios(current: dict[str, float], answers: dict[str, int],
                    scenarios: list[dict] | None = None) -> dict[str, float]:
    """
    Apply scenario answers ON TOP of the user's current vector (incremental
    refinement). `scenarios` is the exact set the user was shown (e.g. an
    LLM-generated batch); falls back to the curated pool when not given.
    answers: {scenario_id: option_index}. Returns a clamped vector.
    """
    vec = {t: float(current.get(t, 0.5)) for t in TRAITS}
    by_id = {s["id"]: s for s in (scenarios if scenarios is not None else SCENARIOS)}
    for sid, opt_idx in (answers or {}).items():
        s = by_id.get(sid)
        if s is None:
            continue
        try:
            option = s["options"][int(opt_idx)]
        except (IndexError, ValueError, TypeError):
            continue
        for trait, delta in option.get("deltas", {}).items():
            if trait in vec:
                vec[trait] += delta
    return {t: clamp01(v) for t, v in vec.items()}
