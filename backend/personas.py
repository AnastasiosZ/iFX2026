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
            "risk_tolerance": 0.15, "risk_aversion": 0.9, "patience": 0.85,
            "impulsivity": 0.15, "discipline": 0.8, "greed": 0.2,
            "confidence": 0.4, "analytical_depth": 0.5, "contrarian_tendency": 0.3,
            "herd_mentality": 0.55,
        }),
        "basket": ["BND", "SHY", "TLT", "PG", "KO", "JNJ", "VTI", "GLD"],
    },
    {
        "id": "index_autopilot",
        "name": "The Index Autopilot",
        "blurb": "Buys the whole market monthly and ignores the noise.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.45, "risk_aversion": 0.5, "patience": 0.9,
            "impulsivity": 0.1, "discipline": 0.9, "greed": 0.3,
            "confidence": 0.5, "analytical_depth": 0.4, "contrarian_tendency": 0.3,
            "herd_mentality": 0.6,
        }),
        "basket": ["VTI", "SPY", "QQQ", "BND", "AAPL", "MSFT"],
    },
    {
        "id": "value_investor",
        "name": "The Value Investor",
        "blurb": "Reads the 10-K cover to cover. Buys wonderful companies at fair prices.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.5, "risk_aversion": 0.55, "patience": 0.9,
            "impulsivity": 0.1, "discipline": 0.85, "greed": 0.35,
            "confidence": 0.7, "analytical_depth": 0.95, "contrarian_tendency": 0.65,
            "herd_mentality": 0.2,
        }),
        "basket": ["BRK-B", "JPM", "JNJ", "AAPL", "MSFT", "GOOGL", "PG"],
    },
    {
        "id": "growth_hunter",
        "name": "The Growth Hunter",
        "blurb": "Wants the next 10x. Tolerates drawdowns for upside.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.85, "risk_aversion": 0.2, "patience": 0.55,
            "impulsivity": 0.45, "discipline": 0.55, "greed": 0.7,
            "confidence": 0.8, "analytical_depth": 0.7, "contrarian_tendency": 0.5,
            "herd_mentality": 0.4,
        }),
        "basket": ["NVDA", "AMD", "META", "NFLX", "PLTR", "QQQ", "GOOGL"],
    },
    {
        "id": "degen",
        "name": "The Degen",
        "blurb": "High conviction, high adrenaline. YOLOs into momentum.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.95, "risk_aversion": 0.1, "patience": 0.2,
            "impulsivity": 0.85, "discipline": 0.25, "greed": 0.9,
            "confidence": 0.85, "analytical_depth": 0.35, "contrarian_tendency": 0.4,
            "herd_mentality": 0.65,
        }),
        "basket": ["TSLA", "GME", "COIN", "DOGE-USD", "SOL-USD", "PLTR", "ARKK"],
    },
    {
        "id": "crypto_native",
        "name": "The Crypto Native",
        "blurb": "Believes in the tech, stomachs the volatility, stacks sats.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.85, "risk_aversion": 0.2, "patience": 0.6,
            "impulsivity": 0.5, "discipline": 0.5, "greed": 0.7,
            "confidence": 0.75, "analytical_depth": 0.6, "contrarian_tendency": 0.7,
            "herd_mentality": 0.45,
        }),
        "basket": ["BTC-USD", "ETH-USD", "SOL-USD", "COIN", "NVDA"],
    },
    {
        "id": "contrarian",
        "name": "The Contrarian",
        "blurb": "When there's blood in the streets, they're buying.",
        "traits": sanitize_vector({
            "risk_tolerance": 0.7, "risk_aversion": 0.35, "patience": 0.75,
            "impulsivity": 0.3, "discipline": 0.7, "greed": 0.5,
            "confidence": 0.85, "analytical_depth": 0.85, "contrarian_tendency": 0.95,
            "herd_mentality": 0.05,
        }),
        "basket": ["GLD", "TLT", "GME", "ARKK", "BRK-B", "HYG"],
    },
]
