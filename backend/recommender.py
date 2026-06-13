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

The deck itself is not returned as a frozen argsort: instrument cosine
similarities are used as logits in a low-temperature softmax that we SAMPLE
from (Gumbel-top-k), so strong matches lead but the deck stays fresh between
visits. No training, no GPU — pure numpy, and every card still carries an
explainable 'why'.
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
# Step size for nudging the personality vector per swipe. This is the L2 distance
# a *maximally surprising* swipe moves the vector (scaled down by how expected the
# swipe was and by time decay — see effective_vector). It is a unit-direction step,
# not proportional to the raw distance to the instrument, so a pass on a high-match
# card actually shifts the profile instead of vanishing.
SWIPE_LR = 0.15
# Blend weights for the final score. The collaborative term is downweighted: in
# this demo it is entirely persona-basket-derived (the basket signal uses the
# hand-authored baskets directly, and the same-persona crowd signal aggregates
# likes from dummy users that were themselves seeded from those baskets), so it
# is a low-quality, self-referential signal. Content (cosine fit to the user's
# own personality) carries the recommendation; collab only nudges.
W_CONTENT = 0.8
W_COLLAB = 0.2
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
        Base personality nudged by decayed implicit feedback. Each swipe moves
        the vector a fixed-size step ALONG the unit direction toward a liked
        instrument (or away from a passed one), scaled by how *surprising* the
        swipe was — i.e. by the current prediction error. Liking a poor match or
        passing on a strong one contradicts the current vector and so shifts it
        a lot; confirming swipes (liking an already-good match) barely move it.

        The earlier version moved by SWIPE_LR * (target - v), i.e. proportional
        to the raw distance to the instrument. That made a pass on a high-match
        card — which sits right next to the user's vector — barely move anything,
        so disliking strong matches had almost no effect. The unit-step form fixes
        that: the move size comes from the surprise term, not the distance.

        Surprise is measured with Pearson correlation, not raw cosine: trait
        vectors all sit in the positive orthant, so cosine bunches near 1 and
        would deem almost everything a "good match"; centering (Pearson) restores
        real contrast (the same reason persona matching uses it). Recent swipes
        dominate via exponential time decay.
        """
        v = _vec(self.base_vector)
        now = time.time()
        for sw in self.swipes:
            inst = INSTRUMENTS_BY_SYMBOL.get(sw.symbol)
            if inst is None:
                continue
            target = _vec(inst["trait_vector"])
            diff = target - v
            dist = float(np.linalg.norm(diff))
            if dist < 1e-9:
                continue
            age = max(now - sw.ts, 0.0)
            decay = 0.5 ** (age / SWIPE_HALFLIFE_S)
            align = (pearson(v, target) + 1) / 2          # current fit, 0..1
            surprise = (1.0 - align) if sw.liked else align
            sign = 1.0 if sw.liked else -1.0
            v = v + SWIPE_LR * decay * surprise * sign * (diff / dist)
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


# Temperature for the persona-classification softmax. Persona vectors all live in
# a similar region of the space, so raw cosine similarities bunch up in the high
# 0.8s–0.9s and the resulting "match %" looked almost identical across types. We
# instead turn the similarities into a probability distribution with a low
# temperature, which sharpens the contrast so the dominant persona clearly leads
# and the others fan out beneath it (req #19).
PERSONA_SOFTMAX_TAU = 0.028


def nearest_personas(user_vec: dict[str, float], k: int = K_PERSONAS) -> list[dict]:
    u = _vec(user_vec)
    scored = [(pearson(u, pv), p) for (p, pv) in _PERSONA_VECS]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Softmax over ALL personas' similarities -> a spread-out probability that the
    # user belongs to each type. Subtract the max for numerical stability.
    sims = [s for s, _ in scored]
    top = sims[0] if sims else 0.0
    exps = [math.exp((s - top) / PERSONA_SOFTMAX_TAU) for s in sims]
    total = sum(exps) or 1.0
    probs = [e / total for e in exps]

    out = []
    for (sim, p), prob in list(zip(scored, probs))[:k]:
        out.append({
            "id": p["id"],
            "name": p["name"],
            "blurb": p["blurb"],
            "match": round(prob * 100),
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


# Temperature for sampling the recommendation deck. Rather than always returning
# the highest-match cards, we treat each instrument's cosine similarity to the
# user as a logit, divide by this (low) temperature and SAMPLE the deck from the
# resulting softmax distribution. Low tau keeps strong matches dominant while
# still varying the deck between visits, so the user isn't shown an identical,
# frozen ranking every time. Lower -> greedier (approaches pure argsort); higher
# -> more exploratory. Cosine similarities here bunch in a narrow high band, so
# a small tau is needed to produce meaningful spread.
RECOMMEND_SOFTMAX_TAU = 0.05

# Process-wide RNG for deck sampling. Module-level so it isn't reseeded per call.
_rng = np.random.default_rng()


def _sample_order(logits: np.ndarray, tau: float) -> np.ndarray:
    """
    Sample an ordering of items (best-first) from softmax(logits / tau) WITHOUT
    replacement, via the Gumbel-top-k trick: perturb each logit with i.i.d.
    Gumbel(0,1) noise and argsort descending. This is exactly equivalent to
    sequential Plackett-Luce sampling from the softmax, so the lead card is drawn
    proportional to its softmax probability and so on down the deck. With tau<=0
    (or no items) it degenerates to a deterministic argsort by logit.
    """
    n = len(logits)
    if n == 0:
        return np.empty(0, dtype=int)
    if tau <= 0:
        return np.argsort(-logits)
    z = logits / tau
    z = z - z.max()  # softmax is shift-invariant; subtract max for stability
    # Gumbel(0,1) = -log(-log(U)); the epsilons guard against log(0).
    u = _rng.random(n)
    gumbel = -np.log(-np.log(u + 1e-12) + 1e-12)
    return np.argsort(-(z + gumbel))


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
        cos = cosine(u, ivec)                         # raw cosine, the sampling logit
        content = (cos + 1) / 2                        # -> [0,1] for the blended match
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
            "_cosine": cos,
            "_collab": collab_s,
            "_crowd": crowd_s,
            "already_swiped": inst["symbol"] in swiped,
            "why": _explain(uvec, inst, content, basket_s, crowd_s),
        })

    if not rows:
        return []
    # Don't just return the top-`limit` by match: sample the deck from a
    # low-temperature softmax over cosine similarity (the content logit), so the
    # ordering is personalized but stochastic — strong matches lead most of the
    # time, weaker ones surface occasionally, and the deck varies between visits.
    logits = np.array([r["_cosine"] for r in rows], dtype=float)
    order = _sample_order(logits, RECOMMEND_SOFTMAX_TAU)
    return [rows[i] for i in order[:limit]]


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
    """
    A specific, instrument-grounded reason for the recommendation. Names the
    trait that aligns, ties it to a concrete property of THIS instrument (its
    volatility band, 1-year move and reputation), and adds the crowd signal —
    so the user understands exactly why this card surfaced (req #7).
    """
    ivec = inst["trait_vector"]
    # find the trait where user and instrument are both high and close
    best_trait, best_align = None, -1.0
    for t in TRAITS:
        align = (uvec[t] * ivec[t])  # both-high alignment
        if t in _POSITIVE_HIGH and align > best_align:
            best_align, best_trait = align, t

    meta = inst.get("metadata", {})
    risk_band = meta.get("risk_band")
    ret = inst.get("period_return")
    rep = inst.get("reputation", 0.5)

    parts = []
    if best_trait and best_align > 0.3:
        # Tie the matched trait to a concrete instrument property.
        if best_trait in ("risk_tolerance", "greed", "confidence") and risk_band in ("high", "very high"):
            parts.append(f"its {risk_band}-risk profile speaks to your {_POSITIVE_HIGH[best_trait]}")
        elif best_trait in ("risk_aversion", "patience", "discipline") and risk_band in ("low", "very low"):
            parts.append(f"its {risk_band}-risk, steady profile suits your {_POSITIVE_HIGH[best_trait]}")
        elif best_trait == "contrarian_tendency" and rep < 0.55:
            parts.append(f"an out-of-favour name that fits your {_POSITIVE_HIGH[best_trait]}")
        else:
            parts.append(f"it matches your {_POSITIVE_HIGH[best_trait]}")

    if ret is not None and ret >= 0.25:
        parts.append(f"strong 1-year run of +{round(ret * 100)}%")
    elif ret is not None and ret <= -0.1:
        parts.append(f"beaten-down 1-year move of {round(ret * 100)}%")

    if crowd > 0.5:
        parts.append("a favourite among users who share your trader DNA")
    elif basket > 0.4:
        parts.append("popular with traders like you")

    if not parts:
        parts.append("a balanced fit for your overall profile")
    return "; ".join(parts).capitalize()
