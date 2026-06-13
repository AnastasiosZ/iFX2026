"""
Data-prep: pull real market data via yfinance for a curated instrument set,
compute slider scores (volatility / stability / reputation) and a projection
into the 10-dim personality trait space, then write data/instruments.json.

Run:  python -m backend.build_instruments
Falls back to bundled synthetic stats if yfinance is unavailable or offline,
so the demo never depends on a live network at judging time.

This is intentionally a build step, not a runtime dependency: the API reads
the cached JSON. Re-run it once before the demo to refresh prices.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from .traits import TRAITS, clamp01

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = DATA_DIR / "instruments.json"

# Curated demo universe. asset_class drives the UI sectioning
# (stocks / etf / bond / crypto / cfd). ~30 instruments is plenty for a
# convincing demo. `fallback` holds offline stats (annualized vol, ~1y return).
UNIVERSE: list[dict] = [
    # --- Mega-cap / blue chip stocks ---
    {"symbol": "AAPL", "name": "Apple", "asset_class": "stock", "sector": "Tech", "reputation": 0.95, "fallback": {"vol": 0.28, "ret": 0.18}},
    {"symbol": "MSFT", "name": "Microsoft", "asset_class": "stock", "sector": "Tech", "reputation": 0.95, "fallback": {"vol": 0.26, "ret": 0.20}},
    {"symbol": "GOOGL", "name": "Alphabet", "asset_class": "stock", "sector": "Tech", "reputation": 0.92, "fallback": {"vol": 0.30, "ret": 0.22}},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "asset_class": "stock", "sector": "Healthcare", "reputation": 0.9, "fallback": {"vol": 0.16, "ret": 0.04}},
    {"symbol": "PG", "name": "Procter & Gamble", "asset_class": "stock", "sector": "Consumer", "reputation": 0.88, "fallback": {"vol": 0.15, "ret": 0.06}},
    {"symbol": "KO", "name": "Coca-Cola", "asset_class": "stock", "sector": "Consumer", "reputation": 0.87, "fallback": {"vol": 0.15, "ret": 0.05}},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway", "asset_class": "stock", "sector": "Financials", "reputation": 0.93, "fallback": {"vol": 0.18, "ret": 0.14}},
    {"symbol": "JPM", "name": "JPMorgan Chase", "asset_class": "stock", "sector": "Financials", "reputation": 0.85, "fallback": {"vol": 0.24, "ret": 0.16}},
    # --- Growth / higher-volatility stocks ---
    {"symbol": "NVDA", "name": "NVIDIA", "asset_class": "stock", "sector": "Tech", "reputation": 0.9, "fallback": {"vol": 0.50, "ret": 0.9}},
    {"symbol": "TSLA", "name": "Tesla", "asset_class": "stock", "sector": "Auto", "reputation": 0.78, "fallback": {"vol": 0.60, "ret": 0.1}},
    {"symbol": "AMD", "name": "AMD", "asset_class": "stock", "sector": "Tech", "reputation": 0.8, "fallback": {"vol": 0.52, "ret": 0.3}},
    {"symbol": "META", "name": "Meta Platforms", "asset_class": "stock", "sector": "Tech", "reputation": 0.82, "fallback": {"vol": 0.42, "ret": 0.35}},
    {"symbol": "NFLX", "name": "Netflix", "asset_class": "stock", "sector": "Media", "reputation": 0.8, "fallback": {"vol": 0.40, "ret": 0.4}},
    {"symbol": "COIN", "name": "Coinbase", "asset_class": "stock", "sector": "Crypto/Fin", "reputation": 0.6, "fallback": {"vol": 0.85, "ret": 0.2}},
    {"symbol": "PLTR", "name": "Palantir", "asset_class": "stock", "sector": "Tech", "reputation": 0.62, "fallback": {"vol": 0.65, "ret": 0.5}},
    {"symbol": "GME", "name": "GameStop", "asset_class": "stock", "sector": "Retail", "reputation": 0.4, "fallback": {"vol": 0.9, "ret": -0.1}},
    # --- ETFs ---
    {"symbol": "SPY", "name": "S&P 500 ETF", "asset_class": "etf", "sector": "Broad", "reputation": 0.97, "fallback": {"vol": 0.16, "ret": 0.12}},
    {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "asset_class": "etf", "sector": "Tech", "reputation": 0.93, "fallback": {"vol": 0.22, "ret": 0.18}},
    {"symbol": "VTI", "name": "Total US Market ETF", "asset_class": "etf", "sector": "Broad", "reputation": 0.95, "fallback": {"vol": 0.16, "ret": 0.11}},
    {"symbol": "ARKK", "name": "ARK Innovation ETF", "asset_class": "etf", "sector": "Innovation", "reputation": 0.55, "fallback": {"vol": 0.55, "ret": 0.0}},
    {"symbol": "GLD", "name": "Gold ETF", "asset_class": "etf", "sector": "Commodity", "reputation": 0.85, "fallback": {"vol": 0.14, "ret": 0.1}},
    # --- Bonds (proxied via bond ETFs for price history) ---
    {"symbol": "TLT", "name": "20+ Yr Treasury Bond ETF", "asset_class": "bond", "sector": "Govt Bond", "reputation": 0.9, "fallback": {"vol": 0.16, "ret": -0.02}},
    {"symbol": "BND", "name": "Total Bond Market ETF", "asset_class": "bond", "sector": "Aggregate", "reputation": 0.92, "fallback": {"vol": 0.07, "ret": 0.02}},
    {"symbol": "HYG", "name": "High-Yield Corp Bond ETF", "asset_class": "bond", "sector": "Junk Bond", "reputation": 0.7, "fallback": {"vol": 0.1, "ret": 0.05}},
    {"symbol": "SHY", "name": "1-3 Yr Treasury ETF", "asset_class": "bond", "sector": "Short Govt", "reputation": 0.93, "fallback": {"vol": 0.02, "ret": 0.03}},
    # --- Crypto ---
    {"symbol": "BTC-USD", "name": "Bitcoin", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.7, "fallback": {"vol": 0.65, "ret": 0.5}},
    {"symbol": "ETH-USD", "name": "Ethereum", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.65, "fallback": {"vol": 0.75, "ret": 0.4}},
    {"symbol": "DOGE-USD", "name": "Dogecoin", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.3, "fallback": {"vol": 1.1, "ret": -0.2}},
    {"symbol": "SOL-USD", "name": "Solana", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.45, "fallback": {"vol": 0.95, "ret": 0.6}},
]


def _annualized_vol_and_return(closes: list[float]) -> tuple[float, float]:
    """Annualized volatility (std of daily log returns) and total period return."""
    if len(closes) < 2:
        return 0.2, 0.0
    rets = []
    for a, b in zip(closes[:-1], closes[1:]):
        if a > 0 and b > 0:
            rets.append(math.log(b / a))
    if not rets:
        return 0.2, 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    daily_std = math.sqrt(var)
    ann_vol = daily_std * math.sqrt(252)
    total_return = (closes[-1] / closes[0]) - 1.0
    return ann_vol, total_return


def _project_to_traits(vol: float, ret: float, reputation: float, asset_class: str) -> dict[str, float]:
    """
    Map instrument stats into the personality space. The mapping encodes the
    product thesis: which kind of trader an instrument 'fits'. Values in [0,1].

    Intuition:
      - high volatility  -> appeals to risk_tolerance, greed, impulsivity, confidence
      - low volatility   -> appeals to risk_aversion, patience, discipline
      - high reputation  -> appeals to herd_mentality (everyone owns it), risk_aversion
      - low reputation   -> appeals to contrarian_tendency
      - bonds/short govt -> strongly patient / risk-averse / disciplined
    """
    # Normalize volatility onto ~[0,1] (1.0 vol annualized is very high).
    v = clamp01(vol / 0.8)
    rep = clamp01(reputation)

    vec = {
        "risk_tolerance": clamp01(0.15 + 0.8 * v),
        "risk_aversion": clamp01(0.9 - 0.8 * v),
        "patience": clamp01(0.75 - 0.5 * v),
        "impulsivity": clamp01(0.2 + 0.6 * v),
        "discipline": clamp01(0.65 - 0.3 * v),
        "greed": clamp01(0.1 + 0.7 * v + 0.2 * clamp01(ret)),
        "confidence": clamp01(0.35 + 0.4 * v),
        "analytical_depth": 0.5,  # neutral; not strongly implied by price stats
        "contrarian_tendency": clamp01(0.2 + 0.7 * (1.0 - rep)),
        "herd_mentality": clamp01(0.2 + 0.7 * rep),
    }

    if asset_class == "bond":
        vec["patience"] = clamp01(vec["patience"] + 0.25)
        vec["risk_aversion"] = clamp01(vec["risk_aversion"] + 0.2)
        vec["discipline"] = clamp01(vec["discipline"] + 0.2)
        vec["greed"] = clamp01(vec["greed"] - 0.2)
    if asset_class == "crypto":
        vec["contrarian_tendency"] = clamp01(vec["contrarian_tendency"] + 0.1)
        vec["impulsivity"] = clamp01(vec["impulsivity"] + 0.1)

    return {t: round(vec[t], 4) for t in TRAITS}


def _scores_for_ui(vol: float, reputation: float) -> dict[str, float]:
    """The 0-100 slider scores shown on the instrument detail card."""
    volatility = clamp01(vol / 0.8)
    return {
        "volatility": round(100 * volatility),
        "stability": round(100 * (1 - volatility)),
        "reputation": round(100 * clamp01(reputation)),
    }


def _fetch_prices(symbols: list[str]) -> dict[str, list[float]]:
    """Best-effort price history via yfinance. Returns {symbol: [closes]}.
    Any failure yields an empty dict and callers fall back to bundled stats."""
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        print("[build_instruments] yfinance not installed; using fallback stats.")
        return {}
    try:
        data = yf.download(
            symbols, period="1y", interval="1d",
            auto_adjust=True, progress=False, group_by="ticker", threads=True,
        )
    except Exception as e:  # network / rate-limit / API change
        print(f"[build_instruments] yfinance download failed ({e}); using fallback stats.")
        return {}

    out: dict[str, list[float]] = {}
    for sym in symbols:
        try:
            col = data[sym]["Close"] if sym in data.columns.get_level_values(0) else None
            if col is None:
                continue
            closes = [float(x) for x in col.dropna().tolist()]
            if len(closes) >= 20:
                out[sym] = closes
        except Exception:
            continue
    return out


def _sparkline(closes: list[float], n: int = 60) -> list[float]:
    """Downsample a price series to ~n points for the UI chart."""
    if not closes:
        return []
    if len(closes) <= n:
        return [round(c, 2) for c in closes]
    step = len(closes) / n
    return [round(closes[int(i * step)], 2) for i in range(n)]


def build() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    symbols = [u["symbol"] for u in UNIVERSE]
    prices = _fetch_prices(symbols)
    n_live = len(prices)
    print(f"[build_instruments] live price series fetched: {n_live}/{len(symbols)}")

    instruments = []
    for u in UNIVERSE:
        closes = prices.get(u["symbol"], [])
        if closes:
            vol, ret = _annualized_vol_and_return(closes)
            spark = _sparkline(closes)
            source = "live"
        else:
            vol, ret = u["fallback"]["vol"], u["fallback"]["ret"]
            spark = _synthetic_spark(vol, ret)
            source = "fallback"

        instruments.append({
            "symbol": u["symbol"],
            "name": u["name"],
            "asset_class": u["asset_class"],
            "sector": u["sector"],
            "description": _describe(u, vol, ret),
            "scores": _scores_for_ui(vol, u["reputation"]),
            "annualized_volatility": round(vol, 4),
            "period_return": round(ret, 4),
            "trait_vector": _project_to_traits(vol, ret, u["reputation"], u["asset_class"]),
            "sparkline": spark,
            "data_source": source,
        })

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"instruments": instruments}, f, indent=2)
    print(f"[build_instruments] wrote {len(instruments)} instruments -> {OUT_PATH}")
    return instruments


def _describe(u: dict, vol: float, ret: float) -> str:
    risk = "high" if vol > 0.5 else "moderate" if vol > 0.22 else "low"
    klass = {
        "stock": "stock", "etf": "ETF", "bond": "bond/bond fund",
        "crypto": "cryptocurrency", "cfd": "CFD",
    }.get(u["asset_class"], u["asset_class"])
    return (
        f"{u['name']} ({u['symbol']}) — a {u['sector']} {klass} with {risk} volatility. "
        f"Reputation among investors is {'very strong' if u['reputation'] > 0.85 else 'solid' if u['reputation'] > 0.6 else 'speculative'}."
    )


def _synthetic_spark(vol: float, ret: float, n: int = 60) -> list[float]:
    """Deterministic pseudo price path for offline mode (seeded by vol/ret)."""
    import random
    rng = random.Random(int((vol * 1000 + ret * 100)))
    price = 100.0
    drift = ret / n
    daily_vol = vol / math.sqrt(252)
    out = [round(price, 2)]
    for _ in range(n - 1):
        price *= (1 + drift + rng.gauss(0, daily_vol) * math.sqrt(252 / n))
        out.append(round(max(price, 1.0), 2))
    return out


if __name__ == "__main__":
    build()
