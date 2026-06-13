"""
Hand-authored trader archetypes ("seed personas").

These substitute for the proprietary (personality -> trades) dataset that does
not exist publicly and cannot be collected in 24h. Each persona has a trait
vector and a basket of instruments they "invested in". At recommend time we
find the personas nearest to the user and surface their baskets as the
collaborative-filtering signal — i.e. the literal "traders like you invested
in X" feature — alongside the content-based instrument similarity.
"""

from __future__ import annotations

from .traits import sanitize_vector

# Trait vectors are partial; unspecified traits default to 0.5 via sanitize.
PERSONAS: list[dict] = [
    {
        "id": "cautious_saver",
        "name": "The Cautious Saver",
        "blurb": "Sleeps well, never checks the ticker. Capital preservation first.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.10, "risk_aversion": 0.95, "patience": 0.85,
            "impulsivity": 0.10, "discipline": 0.80, "greed": 0.10,
            "confidence": 0.35, "analytical_depth": 0.45, "contrarian_tendency": 0.30,
            "herd_mentality": 0.55,
        }),
        "basket": ["BND", "SHY", "TLT", "PG", "KO", "JNJ", "VTI", "GLD"],
    },
    {
        "id": "index_autopilot",
        "name": "The Index Autopilot",
        "blurb": "Buys the whole market monthly and ignores the noise.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.50, "risk_aversion": 0.45, "patience": 0.95,
            "impulsivity": 0.10, "discipline": 0.90, "greed": 0.25,
            "confidence": 0.30, "analytical_depth": 0.10, "contrarian_tendency": 0.15,
            "herd_mentality": 0.90,
        }),
        "basket": ["VTI", "SPY", "QQQ", "BND", "AAPL", "MSFT"],
    },
    {
        "id": "value_investor",
        "name": "The Value Investor",
        "blurb": "Reads the 10-K cover to cover. Buys wonderful companies at fair prices.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.40, "risk_aversion": 0.60, "patience": 0.90,
            "impulsivity": 0.10, "discipline": 0.90, "greed": 0.30,
            "confidence": 0.65, "analytical_depth": 0.95, "contrarian_tendency": 0.30,
            "herd_mentality": 0.50,
        }),
        "basket": ["BRK-B", "JPM", "JNJ", "AAPL", "MSFT", "GOOGL", "PG"],
    },
    {
        "id": "growth_hunter",
        "name": "The Growth Hunter",
        "blurb": "Wants the next 10x. Tolerates drawdowns for upside.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.85, "risk_aversion": 0.20, "patience": 0.45,
            "impulsivity": 0.55, "discipline": 0.45, "greed": 0.80,
            "confidence": 0.80, "analytical_depth": 0.55, "contrarian_tendency": 0.30,
            "herd_mentality": 0.70,
        }),
        "basket": ["NVDA", "AMD", "META", "NFLX", "PLTR", "QQQ", "GOOGL"],
    },
    {
        "id": "degen",
        "name": "The Degen",
        "blurb": "High conviction, high adrenaline. YOLOs into momentum.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.98, "risk_aversion": 0.05, "patience": 0.10,
            "impulsivity": 0.95, "discipline": 0.15, "greed": 0.95,
            "confidence": 0.85, "analytical_depth": 0.20, "contrarian_tendency": 0.35,
            "herd_mentality": 0.80,
        }),
        "basket": ["TSLA", "GME", "COIN", "DOGE-USD", "SOL-USD", "PLTR", "ARKK"],
    },
    {
        "id": "crypto_native",
        "name": "The Crypto Native",
        "blurb": "Believes in the tech, stomachs the volatility, stacks sats.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.85, "risk_aversion": 0.20, "patience": 0.60,
            "impulsivity": 0.40, "discipline": 0.40, "greed": 0.70,
            "confidence": 0.78, "analytical_depth": 0.72, "contrarian_tendency": 0.80,
            "herd_mentality": 0.20,
        }),
        "basket": ["BTC-USD", "ETH-USD", "SOL-USD", "COIN", "NVDA"],
    },
    {
        "id": "contrarian",
        "name": "The Contrarian",
        "blurb": "When there's blood in the streets, they're buying.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.55, "risk_aversion": 0.40, "patience": 0.90,
            "impulsivity": 0.15, "discipline": 0.90, "greed": 0.30,
            "confidence": 0.90, "analytical_depth": 0.92, "contrarian_tendency": 0.98,
            "herd_mentality": 0.05,
        }),
        "basket": ["GLD", "TLT", "GME", "ARKK", "BRK-B", "HYG"],
    },
]
