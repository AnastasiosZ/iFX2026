"""
The recommender core.

Two blended signals, both computed in the shared 10-dim personality space:

  1. CONTENT-BASED: cosine similarity between the user's personality vector and
     each instrument's trait projection. "This instrument fits who you are."

  2. COLLABORATIVE (persona-based): find the nearest seed personas to the user
     and boost the instruments in their baskets. "Traders like you invested in
     this." This is what makes the recommendation feel social without needing a
     real user-behavior dataset.

Plus an IMPLICIT-FEEDBACK term: as the user swipes, their vector is nudged
toward liked instruments and away from passed ones (with exponential time
decay so recent swipes dominate — the 'decreasing confidence over time' idea
from the brief, applied at inference instead of training).

No training, no GPU. Pure numpy. Deterministic and explainable, which is
exactly what a functionality-first demo needs.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from .traits import TRAITS, N_TRAITS, to_list, from_list, clamp01
from .personas import PERSONAS

# How fast a swipe's influence decays. Half-life in seconds; recent swipes
# weigh more. 1 hour half-life is generous for a demo session.
SWIPE_HALFLIFE_S = 3600.0
# Learning rate for nudging the personality vector per swipe.
SWIPE_LR = 0.08
# Blend weights for the final score.
W_CONTENT = 0.6
W_COLLAB = 0.4
# How many nearest personas contribute to the collaborative signal.
K_PERSONAS = 3


def _vec(d: dict[str, float]) -> np.ndarray:
    return np.array(to_list(d), dtype=float)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


@dataclass
class Swipe:
    symbol: str
    liked: bool
    ts: float = field(default_factory=time.time)


# Within the collaborative signal, how much comes from the baskets of the nearest
# personas vs. from the actual likes of other USERS who share the user's persona.
# Per the product spec: 40% of the collaborative score is the same-persona crowd.
COLLAB_FROM_PERSONA_BASKET = 0.6
COLLAB_FROM_PERSONA_USERS = 0.4


@dataclass
class UserState:
    """Everything we know about one user during a session."""
    base_vector: dict[str, float]            # from questionnaire + interview
    swipes: list[Swipe] = field(default_factory=list)
    user_id: int | None = None               # DB user, once logged in
    persona_id: str | None = None            # assigned persona (DB), for the crowd signal

    def effective_vector(self) -> dict[str, float]:
        """
        base personality nudged by decayed implicit feedback.
        liked instruments pull the vector toward their trait profile;
        passes push it away. Recent swipes dominate via exponential decay.
        """
        v = _vec(self.base_vector)
        now = time.time()
        for sw in self.swipes:
            inst = INSTRUMENTS_BY_SYMBOL.get(sw.symbol)
            if inst is None:
                continue
            age = max(now - sw.ts, 0.0)
            decay = 0.5 ** (age / SWIPE_HALFLIFE_S)
            target = _vec(inst["trait_vector"])
            direction = (target - v) if sw.liked else (v - target)
            v = v + SWIPE_LR * decay * direction
        v = np.clip(v, 0.0, 1.0)
        return from_list(v.tolist())


# --- Module-level instrument index, populated by load() ---
INSTRUMENTS: list[dict] = []
INSTRUMENTS_BY_SYMBOL: dict[str, dict] = {}
_PERSONA_VECS: list[tuple[dict, np.ndarray]] = [(p, _vec(p["traits"])) for p in PERSONAS]


def load(instruments: list[dict]) -> None:
    """Install the instrument universe (called once at startup)."""
    global INSTRUMENTS, INSTRUMENTS_BY_SYMBOL
    INSTRUMENTS = instruments
    INSTRUMENTS_BY_SYMBOL = {i["symbol"]: i for i in instruments}


def nearest_personas(user_vec: dict[str, float], k: int = K_PERSONAS) -> list[dict]:
    u = _vec(user_vec)
    scored = [(pearson(u, pv), p) for (p, pv) in _PERSONA_VECS]
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for sim, p in scored[:k]:
        out.append({
            "id": p["id"],
            "name": p["name"],
            "blurb": p["blurb"],
            "match": round(_to_pct(sim)),
            "basket": p["basket"],
        })
    return out


def _to_pct(cos: float) -> float:
    """Map cosine [-1,1] -> a friendlier 0-100 'match %'."""
    return clamp01((cos + 1) / 2) * 100


def _collab_scores(user_vec: dict[str, float]) -> dict[str, float]:
    """
    Symbol -> collaborative score in [0,1], from nearest personas' baskets,
    weighted by how well each persona matches the user.
    """
    u = _vec(user_vec)
    scored = sorted(
        ((pearson(u, pv), p) for (p, pv) in _PERSONA_VECS),
        key=lambda x: x[0], reverse=True,
    )[:K_PERSONAS]
    if not scored:
        return {}
    weights = {}
    total_w = 0.0
    for sim, p in scored:
        w = max(sim, 0.0)
        total_w += w
        for sym in p["basket"]:
            weights[sym] = weights.get(sym, 0.0) + w
    if total_w > 0:
        for sym in weights:
            weights[sym] = clamp01(weights[sym] / total_w)
    return weights


def _normalize_counts(counts: dict[str, int]) -> dict[str, float]:
    """Like-counts -> [0,1] by dividing by the max count (popularity within crowd)."""
    if not counts:
        return {}
    top = max(counts.values())
    if top <= 0:
        return {}
    return {sym: c / top for sym, c in counts.items()}


def recommend(user: UserState, asset_class: str | None = None, limit: int = 20,
              persona_like_counts: dict[str, int] | None = None) -> list[dict]:
    """
    Ranked recommendations for a user, optionally filtered to one asset class
    (the UI's section tabs). Each item carries its component scores and a short
    human-readable 'why', so the UI can explain every card.

    The collaborative term blends two crowd signals:
      - 60% the baskets of the personas nearest the user's vector, and
      - 40% the instruments actually liked by OTHER users who share this user's
        persona (`persona_like_counts`, symbol -> like count from the DB).
    """
    uvec = user.effective_vector()
    u = _vec(uvec)
    basket = _collab_scores(uvec)
    crowd = _normalize_counts(persona_like_counts or {})
    swiped = {s.symbol for s in user.swipes}

    rows = []
    for inst in INSTRUMENTS:
        if asset_class and inst["asset_class"] != asset_class:
            continue
        ivec = _vec(inst["trait_vector"])
        content = (cosine(u, ivec) + 1) / 2           # -> [0,1]
        basket_s = basket.get(inst["symbol"], 0.0)
        crowd_s = crowd.get(inst["symbol"], 0.0)
        collab_s = COLLAB_FROM_PERSONA_BASKET * basket_s + COLLAB_FROM_PERSONA_USERS * crowd_s
        score = W_CONTENT * content + W_COLLAB * collab_s
        rows.append({
            "symbol": inst["symbol"],
            "name": inst["name"],
            "asset_class": inst["asset_class"],
            "sector": inst["sector"],
            "description": inst["description"],
            "scores": inst["scores"],
            "sparkline": inst["sparkline"],
            "period_return": inst["period_return"],
            "annualized_volatility": inst.get("annualized_volatility"),
            "metadata": inst.get("metadata", {}),
            "strategy": inst.get("strategy", {}),
            "data_source": inst.get("data_source", "fallback"),
            "match": round(score * 100),
            "_content": content,
            "_collab": collab_s,
            "_crowd": crowd_s,
            "already_swiped": inst["symbol"] in swiped,
            "why": _explain(uvec, inst, content, basket_s, crowd_s),
        })

    rows.sort(key=lambda r: r["match"], reverse=True)
    return rows[:limit]


# Traits whose *high* value we phrase positively when explaining a match.
_POSITIVE_HIGH = {
    "risk_tolerance": "appetite for risk",
    "patience": "long-term patience",
    "analytical_depth": "appetite for research",
    "contrarian_tendency": "contrarian streak",
    "discipline": "discipline",
    "risk_aversion": "preference for safety",
    "greed": "drive for returns",
    "confidence": "conviction",
}


def _explain(uvec: dict[str, float], inst: dict, content: float,
             basket: float, crowd: float) -> str:
    """One-line, instrument-specific reason. Picks the trait that aligns most."""
    ivec = inst["trait_vector"]
    # find the trait where user and instrument are both high and close
    best_trait, best_align = None, -1.0
    for t in TRAITS:
        align = (uvec[t] * ivec[t])  # both-high alignment
        if t in _POSITIVE_HIGH and align > best_align:
            best_align, best_trait = align, t
    parts = []
    if best_trait and best_align > 0.3:
        parts.append(f"matches your {_POSITIVE_HIGH[best_trait]}")
    if crowd > 0.5:
        parts.append("a favourite among users with your trader DNA")
    elif basket > 0.4:
        parts.append("popular with traders like you")
    if not parts:
        parts.append("a balanced fit for your profile")
    return "; ".join(parts).capitalize()
