"""
Hand-authored trader archetypes ("seed personas").

These substitute for the proprietary (personality -> trades) dataset that does
not exist publicly and cannot be collected in 24h. Each persona is a point in
the 10-dim trait space plus a basket of instruments that trader would hold.

How they're used:
  - We classify the user against these archetypes (Pearson correlation, softmax)
    and surface the nearest ones as the user's "trader DNA".
  - Their baskets seed the hidden dummy users (db.py), which generate the
    same-persona crowd signal — the "traders like you also liked X" feature.

Design notes (the vectors are deliberately authored, not random):
  - The dominant axis in any honest set of trader archetypes is risk appetite:
    risk_tolerance / greed / impulsivity genuinely co-move, so ~60% of the
    variance lives on that one axis. That is faithful, not a bug.
  - The set is chosen so the remaining axes (analysis, discipline, crowd-
    independence) are each exercised by at least one archetype that DECOUPLES
    them from raw risk — most importantly The Quant (aggressive yet maximally
    disciplined and analytical), which is the archetype a pure risk gradient
    misses. No two archetypes exceed ~0.72 correlation; the closest pairs
    (Growth/Degen, Quant/Contrarian, Saver/Index) are genuine kin, not dupes.

Trait vectors are partial; unspecified traits default to 0.5 via sanitize.
"""

from __future__ import annotations

from .traits import sanitize_vector

PERSONAS: list[dict] = [
    # --- Conservative / passive end (low risk appetite) ---
    {
        "id": "cautious_saver",
        "name": "The Cautious Saver",
        "blurb": "Sleeps well, never checks the ticker. Capital preservation first.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.10, "risk_aversion": 0.95, "patience": 0.74,
            "impulsivity": 0.10, "discipline": 0.78, "greed": 0.10,
            "confidence": 0.30, "analytical_depth": 0.28, "contrarian_tendency": 0.32,
            "herd_mentality": 0.48,
        }),
        "basket": ["BND", "SHY", "BIL", "TLT", "JNJ", "PG", "KO", "GLD"],
    },
    {
        "id": "index_autopilot",
        "name": "The Index Autopilot",
        "blurb": "Buys the whole market monthly and ignores the noise.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.45, "risk_aversion": 0.50, "patience": 0.95,
            "impulsivity": 0.08, "discipline": 0.92, "greed": 0.22,
            "confidence": 0.30, "analytical_depth": 0.06, "contrarian_tendency": 0.10,
            "herd_mentality": 0.95,
        }),
        "basket": ["VTI", "VOO", "SPY", "QQQ", "DIA", "SCHD", "BND"],
    },

    # --- Cerebral / research-driven middle (analysis decoupled from risk) ---
    {
        "id": "value_investor",
        "name": "The Value Investor",
        "blurb": "Reads the 10-K cover to cover. Buys wonderful companies at fair prices.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.40, "risk_aversion": 0.56, "patience": 0.92,
            "impulsivity": 0.10, "discipline": 0.86, "greed": 0.32,
            "confidence": 0.60, "analytical_depth": 0.95, "contrarian_tendency": 0.42,
            "herd_mentality": 0.48,
        }),
        "basket": ["BRK-B", "JPM", "JNJ", "PG", "KO", "UNH", "V", "XOM"],
    },
    {
        "id": "systematic_quant",
        "name": "The Quant",
        "blurb": "Trades a tested system, not a feeling. Aggressive sizing, ironclad rules.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.75, "risk_aversion": 0.25, "patience": 0.50,
            "impulsivity": 0.18, "discipline": 0.97, "greed": 0.50,
            "confidence": 0.82, "analytical_depth": 0.98, "contrarian_tendency": 0.45,
            "herd_mentality": 0.30,
        }),
        "basket": ["SPY", "QQQ", "XLK", "XLF", "IWM", "AAPL", "MSFT", "GLD"],
    },
    {
        "id": "contrarian",
        "name": "The Contrarian",
        "blurb": "When there's blood in the streets, they're buying.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.64, "risk_aversion": 0.36, "patience": 0.82,
            "impulsivity": 0.18, "discipline": 0.80, "greed": 0.32,
            "confidence": 0.96, "analytical_depth": 0.78, "contrarian_tendency": 0.98,
            "herd_mentality": 0.05,
        }),
        "basket": ["GME", "ARKK", "XLE", "HYG", "GLD", "TLT", "BAC"],
    },

    # --- Aggressive end (high risk appetite) ---
    {
        "id": "growth_hunter",
        "name": "The Growth Hunter",
        "blurb": "Wants the next 10x. Tolerates drawdowns for upside.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.85, "risk_aversion": 0.18, "patience": 0.50,
            "impulsivity": 0.45, "discipline": 0.50, "greed": 0.78,
            "confidence": 0.82, "analytical_depth": 0.55, "contrarian_tendency": 0.28,
            "herd_mentality": 0.74,
        }),
        "basket": ["NVDA", "AMD", "META", "NFLX", "PLTR", "AMZN", "TSLA", "QQQ"],
    },
    {
        "id": "degen",
        "name": "The Degen",
        "blurb": "High conviction, high adrenaline. YOLOs into momentum.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.98, "risk_aversion": 0.04, "patience": 0.08,
            "impulsivity": 0.97, "discipline": 0.10, "greed": 0.97,
            "confidence": 0.85, "analytical_depth": 0.15, "contrarian_tendency": 0.28,
            "herd_mentality": 0.85,
        }),
        "basket": ["TSLA", "GME", "COIN", "DOGE-USD", "SHIB-USD", "SOL-USD", "PLTR", "ARKK"],
    },
]
