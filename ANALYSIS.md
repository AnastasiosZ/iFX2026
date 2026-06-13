# Finter — Technical Analysis & Design Rationale

How the "Fintech + Tinder" concept was turned into a working, end-to-end,
demo-safe application in a single build session — and *why* each decision was
made the way it was.

This document is the engineering narrative behind the code. For how to run it,
see [README.md](README.md); for forward-looking guidance, see [CLAUDE.md](CLAUDE.md).

---

## 1. The problem, restated

The brief asked for a mobile app that:

1. Builds a **personality vector** for a user via multiple-choice questions + a
   short AI-agent interview.
2. Lets the user browse investments (stocks, options, bonds, CFDs…).
3. **Recommends instruments based on what similar-personality traders chose**,
   originally via a neural network whose output is a probability distribution
   over instruments, trained with one-/multi-hot labels and a time-decay term.
4. Shows each instrument's description, slider ratings (stability / volatility /
   reputation), and price history.

The hard constraint: **~24 hours**, and judging is *functionality-first*
(originality explicitly does not matter much).

## 2. The decision that shaped everything: don't train the NN

The single most important engineering call was to **not build the neural
network as the core of the MVP**, and to be explicit about why.

The proposed NN learns a mapping:

```
personality vector  ──►  P(instrument chosen by similar traders)
```

To train that, you need a labelled dataset of the form *"a person with
personality X chose to invest in instruments {A, B, C}."* **That dataset does
not exist publicly and cannot be collected in 24 hours.** Any from-scratch
network trained on a tiny or synthetic stand-in would:

- not converge to anything meaningful (too few samples, no signal),
- be **unexplainable** (a black box can't tell a judge *why* it recommended
  something), and worst of all
- be a **live-demo risk** — it might emit garbage in front of the judges.

Given functionality-first judging, betting the demo on an untrained model is the
wrong risk. So the architecture was inverted:

> **Replace the learned `personality → trades` mapping with a *designed* one,
> computed in a single shared vector space, and keep every idea from the brief
> that doesn't depend on training.**

Crucially, **nothing in the concept was thrown away** — personality vectors, the
AI interview, "traders like you," the sliders, price history, and even the
time-decay term all survive. Only the *implementation* of the recommendation
changed: from *learned weights* to *explainable geometry*. The NN becomes a
documented **stretch goal**, and — importantly — the app is designed to
**collect exactly the data that would train it later** (every swipe is a
labelled `(personality, instrument, like/pass)` triple).

## 3. The core idea: one shared 10-dimensional space

Everything rests on a single trick. Both **users** and **instruments** are
represented as vectors in the *same* 10-dimensional personality space (the ten
traits from the original `poc.py`: `risk_tolerance`, `risk_aversion`,
`patience`, `impulsivity`, `discipline`, `greed`, `confidence`,
`analytical_depth`, `contrarian_tendency`, `herd_mentality`).

```
        risk_tolerance ▲
                       │   • NVDA (high-vol growth stock)
                       │  • The Degen (persona)
              ★ user ──┼─ ───────────────►
                       │           • AAPL
                       │   • BND (bond)   • The Cautious Saver
                       ▼
```

Once user and instrument live in the same space, **recommendation is just a
similarity computation** — and similarity in a space whose axes are named human
traits is *inherently explainable*: "recommended because your high
`risk_tolerance` matches this instrument's volatility profile."

This is the conceptual keystone. It's what lets the app be both personalized and
fully transparent, with zero training.

Implementation: [`backend/traits.py`](backend/traits.py) defines the canonical
trait ordering and the `sanitize_vector()` helper used *everywhere* untrusted
data enters (questionnaire scoring, LLM output) to clamp values to `[0,1]`, drop
unknown keys, and default missing traits to `0.5`.

## 4. How each component works

### 4.1 Building the personality vector (two stages)

**Stage 1 — Questionnaire** ([`questionnaire.py`](backend/questionnaire.py)).
Six multiple-choice questions, each option carrying hand-tuned **trait deltas**
applied on top of a neutral `0.5` baseline. This produces a usable vector
instantly and *deterministically*, with no LLM. Example: choosing "Buy more —
it's on sale" after a 20% crash adds to `risk_tolerance`, `contrarian_tendency`,
and `confidence` while subtracting from `risk_aversion`.

**Stage 2 — AI interview** ([`interview.py`](backend/interview.py)). A short
conversational interview whose *only* job is to emit the 10-trait vector. Two
interchangeable backends behind one interface:

- **Local Llama via Ollama** (auto-detected). The conversation is sent to the
  model with a strict instruction to return **only JSON** mapping each trait to
  a `0.0–1.0` score, using the trait descriptions as the scoring rubric. Ollama's
  `format: "json"` option constrains the output, and the response is still
  defensively parsed (regex JSON extraction) and run through `sanitize_vector()`.
  *We never trust the model to stay in range.*
- **Deterministic heuristic** (fallback). A keyword→trait-delta scorer that
  nudges the questionnaire prior based on cues in the user's free text ("hold
  long term" → patience↑, "yolo" → risk_tolerance↑). Crude but **demo-safe**:
  zero external dependencies, always available.

The two backends are selected automatically (`FINTER_LLM=auto`): if Ollama is
reachable it's used, otherwise the heuristic. This is the **live-demo safety
net** — the interview can never break the demo, while still showcasing the local
LLM when hardware permits.

The final vector blends the two stages (interview weighted 0.6 over the
questionnaire prior 0.4) — see `submit_interview` in
[`app.py`](backend/app.py).

### 4.2 Projecting instruments into the trait space

[`build_instruments.py`](backend/build_instruments.py) is a **build step, not a
runtime dependency**: it fetches a curated ~30-instrument universe from
**yfinance** (real prices), computes statistics, and writes
`data/instruments.json`, which the API then just reads.

For each instrument it computes:

- **Annualized volatility** = std of daily log-returns × √252.
- **Period return** over the window.
- **UI slider scores** (0–100): volatility, stability (= inverse volatility),
  reputation (curated per instrument).
- **A trait projection** — the mapping that places the instrument in the user's
  space. This encodes the product thesis of *which kind of trader an instrument
  fits*:
  - high volatility → appeals to `risk_tolerance`, `greed`, `impulsivity`, `confidence`;
  - low volatility → appeals to `risk_aversion`, `patience`, `discipline`;
  - high reputation → appeals to `herd_mentality` (everyone owns it);
  - low reputation → appeals to `contrarian_tendency`;
  - asset-class nudges (bonds → more patient/safe; crypto → more contrarian).

**Resilience was designed in:** every instrument carries bundled `fallback`
stats, and `_fetch_prices` degrades gracefully on *any* failure (yfinance not
installed, offline, rate-limited, API change). In the actual build run, 27/29
symbols came from live data and 2 (`VTI`, `GLD`, which hit a transient
"database is locked" error) silently used fallback stats. **The demo never
depends on a live network at judging time.**

### 4.3 The "traders like you" signal (collaborative, without a dataset)

[`personas.py`](backend/personas.py) defines **seven hand-authored trader
archetypes** — The Cautious Saver, The Index Autopilot, The Value Investor, The
Growth Hunter, The Degen, The Crypto Native, The Contrarian — each with a trait
vector and a **basket** of instruments they "invested in."

These personas are the deliberate substitute for the nonexistent
`(personality → trades)` dataset. At recommend time, the user's nearest personas
(by cosine similarity) contribute their baskets as a collaborative-filtering
signal — *literally* the "traders like you invested in X" feature — weighted by
how well each persona matches the user.

### 4.4 The recommender

[`recommender.py`](backend/recommender.py) blends two signals, both computed in
the shared space:

```
score(user, instrument) = 0.6 · content  +  0.4 · collaborative

  content       = cosine(user_vector, instrument_trait_vector), rescaled to [0,1]
  collaborative = Σ over k-nearest personas owning this instrument,
                  weighted by persona match, normalized to [0,1]
```

Each recommendation is returned with its component scores **and a generated
one-line `why`** (e.g. *"Matches your appetite for risk; popular with traders
like you"*), so the UI can justify every single card — the payoff of the
shared-space design.

### 4.5 The implicit-feedback loop with time decay

This is where the brief's **"decreasing confidence over time"** idea lives —
moved from *training* (where it was proposed) to *inference* (where it's a
one-liner and demos live):

```python
for each past swipe:
    age   = now - swipe.timestamp
    decay = 0.5 ** (age / HALF_LIFE)          # recent swipes weigh more
    target = instrument's trait vector
    direction = (target - v) if liked else (v - target)
    v += LEARNING_RATE * decay * direction     # nudge the personality vector
```

A "like" pulls the user's vector toward the instrument's trait profile; a "pass"
pushes it away; and **exponential time decay** means recent swipes dominate.
This *is* the personalization story — the recommendations visibly adapt as you
swipe — and it required no model training whatsoever. (`effective_vector()` in
[`recommender.py`](backend/recommender.py).)

### 4.6 API and frontend

The FastAPI app ([`app.py`](backend/app.py)) exposes the flow as REST
(`/api/questions`, `/api/session`, `/api/interview`, `/api/recommend`,
`/api/swipe`, `/api/instrument/{sym}`, `/api/profile`) with in-memory sessions
(appropriate for a demo).

The frontend ([`frontend/`](frontend/)) is **single-file vanilla JS — no build
step, no npm** — a deliberate choice to eliminate tooling risk and run on any
judge's laptop or phone browser. It implements the full Tinder-style flow:
welcome → quiz → AI chat interview → an animated **"trader DNA" radar chart** +
persona match cards → a **swipeable card deck** (touch/mouse drag with LIKE/NOPE
stamps) showing price sparklines and slider ratings → watchlist. Charts are
hand-rolled SVG/canvas (no chart library), again to avoid dependencies.

## 5. Why this satisfies the brief while being safe

| Brief requirement | How it's met | Training needed? |
|---|---|---|
| Personality vector from quiz + AI interview | `questionnaire.py` + `interview.py` (Llama or heuristic) | No |
| Browse stocks/bonds/crypto/… with descriptions | Curated universe + asset-class tabs | No |
| Recommend by *similar traders' choices* | Persona baskets (collaborative) + content similarity | No |
| Stability/volatility/reputation sliders | Derived from real price stats in `build_instruments.py` | No |
| Price history | yfinance sparklines (fallback offline) | No |
| Confidence **decay over time** | Exponential decay on swipe feedback, at inference | No |
| Probability distribution over instruments | The blended score *is* a ranking/soft-distribution | No |

Everything the concept cared about is present; the only thing dropped is the
*from-scratch trained network*, which was the infeasible and risky piece.

## 6. Verification performed

The full stack was tested end-to-end before completion:

- **Dependencies** installed cleanly (`requirements.txt`).
- **Data build** ran against live yfinance: **27/29 instruments live**, 2 via
  fallback — proving the resilience path works in practice.
- **Logic test**: a *cautious* answer profile produced recommendations of AAPL,
  JNJ, PG, VTI, BND and matched to *Value Investor / Cautious Saver*; an
  *aggressive* profile produced COIN, SOL, PLTR, NVDA, DOGE and matched to
  *The Degen (98%)*. **The personalities drive clearly different
  recommendations — the central thesis, demonstrated.**
- **Live HTTP test** of every endpoint: health, session creation, interview
  Q&A, recommend (with `why` strings), instrument detail (live 60-point
  sparkline), swipe (profile loop), and static frontend serving — all `200 OK`.
- **Encoding check**: confirmed the API serves clean UTF-8 JSON (em-dashes etc.
  render correctly in the browser; earlier mojibake was only a Windows curl
  stdout artifact, not the payload).

## 7. The honest path to the neural network (if pursued later)

The app is intentionally the **data-collection front-end** for the model the
brief originally wanted. Every swipe yields a labelled triple
`(personality_vector, instrument, liked)`. With enough collected swipes you can:

1. Train a small classifier/ranker with the swipe likes as multi-hot labels
   (the originally-proposed loss), using the personality vector (and instrument
   features) as input.
2. Apply the time-decay term as a **sample weight** during training (recent
   sessions weighted higher) — the same idea, now in its natural place.
3. Blend the learned score into `recommender.py` *alongside* the existing
   content/collaborative terms, so the system degrades gracefully and stays
   explainable.

This ordering — ship the explainable, demo-safe system first; layer learning on
the data it generates second — is the recommended approach in
[CLAUDE.md](CLAUDE.md), and it is exactly the inversion described in §2: do not
*start* with the untrained network; *earn your way* to a trained one.
