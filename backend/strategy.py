"""
Per-instrument strategy generation.

Given an instrument's stats (volatility, return, reputation, asset class) we
produce a short, concrete *suggested approach* — position sizing, holding
horizon, and risk management — phrased for a retail user. This is deterministic
and rule-based so it always renders in the demo; it is NOT investment advice and
the UI says so.

The output is computed at build time and cached on each instrument record, so
the API serves it with zero latency. (An LLM could later rewrite these into
richer prose, but the heuristic is the demo-safe default.)
"""

from __future__ import annotations


def _risk_band(vol: float) -> str:
    if vol >= 0.6:
        return "very high"
    if vol >= 0.4:
        return "high"
    if vol >= 0.22:
        return "moderate"
    if vol >= 0.1:
        return "low"
    return "very low"


def _horizon(asset_class: str, vol: float) -> str:
    if asset_class == "bond":
        return "multi-year, income-oriented"
    if asset_class == "crypto":
        return "long-term conviction with high volatility tolerance"
    if vol >= 0.5:
        return "tactical — actively managed, weeks to months"
    if vol >= 0.25:
        return "medium-term, 1–3 years"
    return "long-term, 3+ years (buy-and-hold)"


def _sizing(vol: float, reputation: float) -> str:
    if vol >= 0.6 or reputation < 0.45:
        return "a small, speculative slice of the portfolio (≈1–3%)"
    if vol >= 0.35:
        return "a measured position (≈3–6%), scaled in over time"
    return "a core holding you can size meaningfully (≈5–10%)"


def _risk_mgmt(vol: float, asset_class: str) -> str:
    if asset_class == "bond":
        return "hold to ladder duration; watch interest-rate moves rather than price ticks"
    if vol >= 0.5:
        return "use a strict stop-loss and take partial profits into strength; avoid leverage"
    if vol >= 0.25:
        return "dollar-cost-average entries and rebalance on big swings"
    return "rebalance periodically; little day-to-day management needed"


def build_strategy(name: str, symbol: str, asset_class: str,
                   vol: float, ret: float, reputation: float) -> dict:
    """Return a structured strategy dict (also flattened to a `text` summary)."""
    risk = _risk_band(vol)
    horizon = _horizon(asset_class, vol)
    sizing = _sizing(vol, reputation)
    risk_mgmt = _risk_mgmt(vol, asset_class)

    trend = "an uptrend" if ret > 0.08 else "a downtrend" if ret < -0.08 else "a sideways trend"
    thesis = (
        f"{name} carries {risk} volatility and has shown {trend} over the past year. "
        f"It suits {horizon.split(',')[0]} investors."
    )

    text = (
        f"Suggested approach: treat {symbol} as {sizing}. "
        f"Horizon: {horizon}. "
        f"Risk management: {risk_mgmt}."
    )

    return {
        "thesis": thesis,
        "horizon": horizon,
        "sizing": sizing,
        "risk_management": risk_mgmt,
        "risk_band": risk,
        "text": text,
    }
