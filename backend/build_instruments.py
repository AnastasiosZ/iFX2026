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
from .strategy import build_strategy

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

    # --- Additional stocks ---
    {"symbol": "AMZN", "name": "Amazon", "asset_class": "stock", "sector": "Consumer", "reputation": 0.9, "fallback": {"vol": 0.33, "ret": 0.25}},
    {"symbol": "V", "name": "Visa", "asset_class": "stock", "sector": "Financials", "reputation": 0.9, "fallback": {"vol": 0.2, "ret": 0.12}},
    {"symbol": "MA", "name": "Mastercard", "asset_class": "stock", "sector": "Financials", "reputation": 0.89, "fallback": {"vol": 0.21, "ret": 0.13}},
    {"symbol": "UNH", "name": "UnitedHealth", "asset_class": "stock", "sector": "Healthcare", "reputation": 0.86, "fallback": {"vol": 0.24, "ret": 0.05}},
    {"symbol": "HD", "name": "Home Depot", "asset_class": "stock", "sector": "Consumer", "reputation": 0.85, "fallback": {"vol": 0.22, "ret": 0.1}},
    {"symbol": "COST", "name": "Costco", "asset_class": "stock", "sector": "Consumer", "reputation": 0.88, "fallback": {"vol": 0.2, "ret": 0.22}},
    {"symbol": "DIS", "name": "Walt Disney", "asset_class": "stock", "sector": "Media", "reputation": 0.8, "fallback": {"vol": 0.3, "ret": 0.02}},
    {"symbol": "BAC", "name": "Bank of America", "asset_class": "stock", "sector": "Financials", "reputation": 0.78, "fallback": {"vol": 0.3, "ret": 0.1}},
    {"symbol": "XOM", "name": "ExxonMobil", "asset_class": "stock", "sector": "Energy", "reputation": 0.8, "fallback": {"vol": 0.26, "ret": 0.08}},
    {"symbol": "CVX", "name": "Chevron", "asset_class": "stock", "sector": "Energy", "reputation": 0.8, "fallback": {"vol": 0.25, "ret": 0.06}},

    # --- Additional ETFs ---
    {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "asset_class": "etf", "sector": "Broad", "reputation": 0.96, "fallback": {"vol": 0.16, "ret": 0.12}},
    {"symbol": "IWM", "name": "Russell 2000 ETF", "asset_class": "etf", "sector": "Small Cap", "reputation": 0.85, "fallback": {"vol": 0.24, "ret": 0.08}},
    {"symbol": "DIA", "name": "Dow Jones ETF", "asset_class": "etf", "sector": "Broad", "reputation": 0.9, "fallback": {"vol": 0.15, "ret": 0.1}},
    {"symbol": "EFA", "name": "MSCI EAFE ETF", "asset_class": "etf", "sector": "Intl Developed", "reputation": 0.84, "fallback": {"vol": 0.17, "ret": 0.07}},
    {"symbol": "EEM", "name": "Emerging Markets ETF", "asset_class": "etf", "sector": "Emerging Mkts", "reputation": 0.75, "fallback": {"vol": 0.22, "ret": 0.04}},
    {"symbol": "XLK", "name": "Technology Sector ETF", "asset_class": "etf", "sector": "Tech", "reputation": 0.86, "fallback": {"vol": 0.26, "ret": 0.2}},
    {"symbol": "XLE", "name": "Energy Sector ETF", "asset_class": "etf", "sector": "Energy", "reputation": 0.78, "fallback": {"vol": 0.3, "ret": 0.06}},
    {"symbol": "XLF", "name": "Financials Sector ETF", "asset_class": "etf", "sector": "Financials", "reputation": 0.8, "fallback": {"vol": 0.24, "ret": 0.1}},
    {"symbol": "VNQ", "name": "Real Estate ETF", "asset_class": "etf", "sector": "Real Estate", "reputation": 0.78, "fallback": {"vol": 0.22, "ret": 0.03}},
    {"symbol": "SCHD", "name": "Dividend Equity ETF", "asset_class": "etf", "sector": "Dividend", "reputation": 0.85, "fallback": {"vol": 0.16, "ret": 0.09}},

    # --- Additional bonds (bond ETFs as proxies) ---
    {"symbol": "IEF", "name": "7-10 Yr Treasury ETF", "asset_class": "bond", "sector": "Govt Bond", "reputation": 0.9, "fallback": {"vol": 0.08, "ret": 0.01}},
    {"symbol": "LQD", "name": "Inv-Grade Corp Bond ETF", "asset_class": "bond", "sector": "Corp Bond", "reputation": 0.85, "fallback": {"vol": 0.09, "ret": 0.03}},
    {"symbol": "AGG", "name": "US Aggregate Bond ETF", "asset_class": "bond", "sector": "Aggregate", "reputation": 0.92, "fallback": {"vol": 0.07, "ret": 0.02}},
    {"symbol": "TIP", "name": "TIPS Bond ETF", "asset_class": "bond", "sector": "Inflation", "reputation": 0.84, "fallback": {"vol": 0.08, "ret": 0.02}},
    {"symbol": "MUB", "name": "Municipal Bond ETF", "asset_class": "bond", "sector": "Muni Bond", "reputation": 0.83, "fallback": {"vol": 0.06, "ret": 0.03}},
    {"symbol": "EMB", "name": "Emerging Mkts Bond ETF", "asset_class": "bond", "sector": "EM Bond", "reputation": 0.7, "fallback": {"vol": 0.11, "ret": 0.04}},
    {"symbol": "VCIT", "name": "Interm Corp Bond ETF", "asset_class": "bond", "sector": "Corp Bond", "reputation": 0.83, "fallback": {"vol": 0.07, "ret": 0.03}},
    {"symbol": "BIL", "name": "1-3 Month T-Bill ETF", "asset_class": "bond", "sector": "T-Bills", "reputation": 0.93, "fallback": {"vol": 0.01, "ret": 0.05}},
    {"symbol": "VGIT", "name": "Interm Treasury ETF", "asset_class": "bond", "sector": "Govt Bond", "reputation": 0.9, "fallback": {"vol": 0.06, "ret": 0.02}},
    {"symbol": "JNK", "name": "High-Yield Bond ETF", "asset_class": "bond", "sector": "Junk Bond", "reputation": 0.68, "fallback": {"vol": 0.1, "ret": 0.05}},

    # --- Additional crypto ---
    {"symbol": "BNB-USD", "name": "BNB", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.6, "fallback": {"vol": 0.7, "ret": 0.3}},
    {"symbol": "XRP-USD", "name": "XRP", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.5, "fallback": {"vol": 0.85, "ret": 0.4}},
    {"symbol": "ADA-USD", "name": "Cardano", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.5, "fallback": {"vol": 0.9, "ret": 0.1}},
    {"symbol": "AVAX-USD", "name": "Avalanche", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.45, "fallback": {"vol": 1.0, "ret": 0.2}},
    {"symbol": "DOT-USD", "name": "Polkadot", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.45, "fallback": {"vol": 0.9, "ret": -0.1}},

    {"symbol": "LTC-USD", "name": "Litecoin", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.5, "fallback": {"vol": 0.8, "ret": 0.05}},
    {"symbol": "LINK-USD", "name": "Chainlink", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.48, "fallback": {"vol": 0.9, "ret": 0.25}},
    {"symbol": "BCH-USD", "name": "Bitcoin Cash", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.45, "fallback": {"vol": 0.85, "ret": 0.3}},
    {"symbol": "SHIB-USD", "name": "Shiba Inu", "asset_class": "crypto", "sector": "Crypto", "reputation": 0.25, "fallback": {"vol": 1.2, "ret": -0.3}},

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

    Three INDEPENDENT signals drive the projection, so the resulting vectors
    occupy real volume in the trait space rather than collapsing onto a single
    volatility axis (the failure mode of the original all-vol mapping):

      1. volatility (v)  -> risk_tolerance/aversion, impulsivity, greed, confidence,
                            and (inversely) patience/discipline. The dominant axis,
                            as it should be: vol is what makes an instrument risky.
      2. momentum (ret)  -> a HOT instrument (big positive return) is crowded and
                            chased: drives herd_mentality, greed, impulsivity. A
                            BEATEN instrument (negative return) is out-of-favor:
                            drives contrarian_tendency and patience. This is what
                            decouples herd from contrarian (they were pure mirrors
                            of reputation before).
      3. asset_class     -> sets the baseline for patience, discipline, and
                            analytical_depth. Single-name stocks reward bottom-up
                            research (high analytical_depth); broad index ETFs are
                            the explicit choice NOT to analyse (low); bonds are
                            patient/disciplined by nature; crypto is impatient and
                            sentiment-driven. This is what brings analytical_depth
                            to life — it was hardcoded to 0.5 (a dead dimension).
    """
    # Normalize volatility onto ~[0,1] (0.8 vol annualized is already very high).
    v = clamp01(vol / 0.8)
    rep = clamp01(reputation)
    # Momentum split into "hot" (chased) and "beaten" (out-of-favour) components.
    up = clamp01(ret / 0.4)      # +40% over the period -> fully "hot"
    dn = clamp01(-ret / 0.25)    # -25% over the period -> fully "beaten"

    # Asset-class baselines for traits that price stats alone don't capture.
    patience_base = {"bond": 0.90, "etf": 0.70, "stock": 0.60, "crypto": 0.45}.get(asset_class, 0.60)
    discipline_base = {"bond": 0.80, "etf": 0.70, "stock": 0.60, "crypto": 0.45}.get(asset_class, 0.60)
    if asset_class == "stock":      # single names reward fundamental analysis; quality most of all
        analytical = 0.50 + 0.30 * rep
    elif asset_class == "etf":      # broad index = anti-analysis; thematic/active (low rep) needs a view
        analytical = 0.60 - 0.35 * rep
    elif asset_class == "bond":     # rates are an allocation call; junk credit needs more homework
        analytical = 0.30 + 0.25 * (1.0 - rep)
    elif asset_class == "crypto":   # BTC/ETH carry a thesis; memecoins are pure sentiment
        analytical = 0.20 + 0.30 * rep
    else:
        analytical = 0.50

    vec = {
        "risk_tolerance": clamp01(0.15 + 0.80 * v),
        "risk_aversion": clamp01(0.90 - 0.80 * v),
        "patience": clamp01(patience_base - 0.40 * v + 0.15 * dn),
        "impulsivity": clamp01(0.20 + 0.45 * v + 0.25 * up),
        "discipline": clamp01(discipline_base - 0.25 * v),
        "greed": clamp01(0.10 + 0.50 * v + 0.35 * up),
        "confidence": clamp01(0.35 + 0.30 * v + 0.15 * up),
        "analytical_depth": clamp01(analytical),
        "contrarian_tendency": clamp01(0.15 + 0.45 * (1.0 - rep) + 0.35 * dn),
        "herd_mentality": clamp01(0.15 + 0.40 * rep + 0.40 * up),
    }

    return {t: round(vec[t], 4) for t in TRAITS}


def _metadata(closes: list[float], spark: list[float], vol: float, ret: float,
              reputation: float, asset_class: str) -> dict:
    """Extra human-facing metadata shown on the instrument detail card."""
    series = closes or spark
    latest = round(series[-1], 2) if series else None
    hi = round(max(series), 2) if series else None
    lo = round(min(series), 2) if series else None
    # Position within the period range, 0 (at low) .. 100 (at high).
    range_pos = None
    if series and hi is not None and lo is not None and hi > lo:
        range_pos = round(100 * (series[-1] - lo) / (hi - lo))
    trend = "uptrend" if ret > 0.08 else "downtrend" if ret < -0.08 else "sideways"
    liquidity = "very high" if reputation > 0.85 else "high" if reputation > 0.6 else "moderate"
    return {
        "latest_price": latest,
        "period_high": hi,
        "period_low": lo,
        "range_position": range_pos,           # 0-100, where in the 1y range we are
        "trend": trend,
        "liquidity": liquidity,
        "risk_band": _risk_band(vol),
        "asset_class_label": {
            "stock": "Stock", "etf": "ETF", "bond": "Bond / Bond fund",
            "crypto": "Cryptocurrency", "cfd": "CFD",
        }.get(asset_class, asset_class.title()),
    }


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
            "reputation": round(u["reputation"], 3),
            "metadata": _metadata(closes, spark, vol, ret, u["reputation"], u["asset_class"]),
            "strategy": build_strategy(u["name"], u["symbol"], u["asset_class"],
                                       vol, ret, u["reputation"]),
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
