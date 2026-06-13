"""
Personality trait space for Finter.

A user is represented as a 10-dimensional vector over these traits, each scored
in [0, 1]. Instruments are projected into the SAME space (see instruments.py)
so that recommendation is a similarity computation in one shared space and is
therefore explainable ("recommended because your high risk_tolerance matches
this instrument's volatility profile").

The descriptions double as the rubric handed to the LLM interviewer.
"""

from __future__ import annotations

# Canonical ordering. Everything (vectors, JSON, the NN-if-we-get-there) keys
# off this list, so order is load-bearing — append, never reorder.
TRAITS: list[str] = [
    "risk_tolerance",
    "risk_aversion",
    "patience",
    "impulsivity",
    "discipline",
    "greed",
    "confidence",
    "analytical_depth",
    "contrarian_tendency",
    "herd_mentality",
]

TRAIT_DESCRIPTIONS: dict[str, str] = {
    "risk_tolerance": "Willingness to accept losses in pursuit of higher returns; comfort with portfolio volatility",
    "risk_aversion": "Preference for stability and capital preservation over aggressive growth strategies",
    "patience": "Ability to hold positions through market fluctuations without impulsive decision-making",
    "impulsivity": "Tendency to make quick trading decisions based on recent price movements or emotional reactions",
    "discipline": "Adherence to a predetermined trading plan and risk management rules regardless of market conditions",
    "greed": "Desire to maximize profits that may override prudent risk management and position sizing",
    "confidence": "Self-belief in trading abilities and market analysis, which can enhance or undermine decision-making",
    "analytical_depth": "Inclination toward detailed research, technical analysis, and data-driven decision-making",
    "contrarian_tendency": "Propensity to go against market consensus and take positions opposing prevailing sentiment",
    "herd_mentality": "Inclination to follow the crowd and base decisions on majority market behavior rather than individual analysis",
}

N_TRAITS = len(TRAITS)


def empty_vector() -> dict[str, float]:
    """A neutral starting personality (everything at 0.5)."""
    return {t: 0.5 for t in TRAITS}


def clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def sanitize_vector(raw: dict | None) -> dict[str, float]:
    """
    Coerce arbitrary input (e.g. LLM output) into a valid trait vector:
    keep only known traits, clamp to [0, 1], fill missing with 0.5.
    """
    out = empty_vector()
    if not isinstance(raw, dict):
        return out
    for t in TRAITS:
        if t in raw:
            try:
                out[t] = clamp01(float(raw[t]))
            except (TypeError, ValueError):
                out[t] = 0.5
    return out


def to_list(vec: dict[str, float]) -> list[float]:
    """Trait dict -> ordered list, for math / model input."""
    return [float(vec.get(t, 0.5)) for t in TRAITS]


def from_list(values: list[float]) -> dict[str, float]:
    """Ordered list -> trait dict."""
    return {t: clamp01(float(v)) for t, v in zip(TRAITS, values)}
