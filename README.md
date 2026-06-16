# 🔥 Finter — Personality-driven investing

<img width="640" height="360" alt="demo" src="https://github.com/user-attachments/assets/0662138b-cd99-4089-aaaf-4534ec6ff33f" />

Swipe your way to investments that match **who you are**.

Finter builds a 10-dimensional *personality vector* for each user from a quick
multiple-choice quiz plus a short AI interview, then recommends instruments
(stocks, ETFs, bonds, crypto) by matching that personality against both the
instruments themselves and a set of trader archetypes — *"traders like you
invested in this."* Every swipe nudges your profile in real time.

Built for **iFX HACK 2026** (Cyprus). Judging is functionality-first, so this
is a complete, runnable, end-to-end demo — no training step, no GPU, no network
required at demo time.

---

## Quick start

```bash
# 1. Install deps (a virtualenv is recommended)
python -m pip install -r requirements.txt

# 2. (Optional) Pre-fetch live market data. Skips gracefully to bundled data
#    if offline. The server also auto-builds this on first run.
python -m backend.build_instruments

# 3. Run the app
python -m uvicorn backend.app:app --reload --port 8000

# 4. Open the demo
#    http://localhost:8000
```

On Windows you can instead double-click / run **`run.cmd`**.

### Optional: local Llama interview

By default the AI interview uses a deterministic heuristic scorer (zero
dependencies, always works). To use a **local Llama** via [Ollama](https://ollama.com):

```bash
ollama pull llama3.1
ollama serve            # in a separate terminal
# then start the app normally — it auto-detects Ollama and the badge shows 🦙
```

The interview asks the model to score the 10 traits as **strict JSON**; output
is validated and clamped regardless of backend. Set `FINTER_LLM=off` to force
the heuristic, or `OLLAMA_MODEL=...` to pick a model.

---

## How it works

```
Quiz answers ─┐
              ├─► base personality vector (10 traits, each 0–1)
AI interview ─┘                │
                               ▼
        ┌────────────── recommendation score ──────────────┐
        │  content:  cosine(user, instrument trait-vector)  │
        │  collab:   nearest trader archetypes' baskets     │
        └───────────────────────────────────────────────────┘
                               │
            each swipe ──► decayed nudge to the vector
            (recent swipes weigh more — the "confidence decay" idea)
```

- **Shared trait space.** Users *and* instruments live in the same 10-dim space
  (see [`backend/traits.py`](backend/traits.py)), so every recommendation is
  explainable ("matches your appetite for risk").
- **Instruments** are projected from real market stats — annualized volatility
  and return drive the trait mapping ([`backend/build_instruments.py`](backend/build_instruments.py)).
- **Archetypes** ([`backend/personas.py`](backend/personas.py)) stand in for a
  real user-behavior dataset and power the social signal.
- **No model training.** The whole thing is similarity + an online feedback
  nudge. Deterministic and demo-safe. A learned model could later be layered on
  top using collected swipes as labels — see [CLAUDE.md](CLAUDE.md).

## Project layout

```
backend/
  traits.py             10-trait space, sanitize/clamp helpers
  questionnaire.py      onboarding MCQs -> baseline vector
  build_instruments.py  yfinance pull -> data/instruments.json (+ trait projection)
  personas.py           hand-authored trader archetypes + baskets
  interview.py          Ollama-or-heuristic -> strict JSON trait vector
  recommender.py        content + collaborative scoring, swipe decay
  app.py                FastAPI: questions / interview / recommend / swipe / detail
frontend/
  index.html style.css app.js   single-page swipe UI (no build step)
data/
  instruments.json      generated cache (git-ignored)
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/health` | status + active LLM backend |
| GET  | `/api/questions` | onboarding questionnaire |
| POST | `/api/session` | create session from quiz answers |
| GET  | `/api/interview/next` | next interview question |
| POST | `/api/interview` | submit transcript → finalize vector |
| GET  | `/api/recommend` | ranked picks (`?asset_class=`) |
| POST | `/api/swipe` | record like/pass → updated profile |
| GET  | `/api/instrument/{sym}` | full instrument detail |
| GET  | `/api/profile` | current vector + nearest archetypes |

## Notes

- Sessions are in-memory — fine for a demo, not production.
- Not investment advice; no real trading is executed.

## Submission
Email to **ifxhack@cocooncreations.net**.
