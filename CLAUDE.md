# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Finter (Fintech + Tinder)

A 24-hour hackathon project for **iFX HACK** (Trading & Fintech Hackathon, Cyprus 2026 — https://cyprus2026.ifxexpo.com/hack/).

**Core idea:** A mobile app that builds a *personality vector* for each user (via multiple-choice questions + a short AI-agent interview), then surfaces investment options (stocks, options, bonds, CFDs) with **personalized recommendations driven by what similar-personality traders chose**. Each instrument has a description, slider ratings (stability / volatility / reputation), and price history. A "Tinder-style" swipe UX is the product hook.

**Judging priority (from NOTES.MD):** *Functionality is the most important; originality/cleverness is not.* Build something that demonstrably works end-to-end. Open-source solutions are explicitly allowed.

**Submission:** Email to `ifxhack@cocooncreations.net`.

## Critical architecture guidance (READ before building the model)

The original brainstorm proposed training a neural network from scratch (softmax over all instruments, one-/multi-hot loss, time-decay weighting, BERT-encoded traits). **For a 24-hour build with no proprietary `(personality → trade)` dataset, do not start here.** That dataset does not exist publicly, and a from-scratch NN trained on a tiny/synthetic set will neither converge meaningfully nor demo reliably. Treat the NN as a *stretch goal*, not the MVP.

**Recommended approach instead — content-based + similarity recommender:**

1. Represent each user as a normalized **10-dim personality vector** over the traits in `poc.py` (`risk_tolerance`, `patience`, `discipline`, `greed`, etc.).
2. Represent each **instrument** as a feature vector in the *same conceptual space* (e.g. volatility → maps to risk_tolerance, dividend stability → patience/discipline, meme/sentiment → herd_mentality). This makes recommendations explainable ("recommended because your high risk-tolerance matches this instrument's volatility profile").
3. Recommend via **cosine similarity / k-NN** between the user vector and instrument vectors, optionally blended with collaborative signals from *seed personas* (a handful of hand-authored archetype users: "The Cautious Saver", "The Degen", "The Value Investor") each pre-assigned a basket of instruments.
4. **Implicit feedback loop:** swipes (right=interested, left=pass), dwell time, and taps adjust the user vector online (simple gradient nudge toward/away from swiped instruments). This *is* the personalization story and demos beautifully without training.
5. Keep the **time-decay** idea as a recency weight on implicit feedback (recent swipes count more) — it's a one-line exponential weight, not a training concern.

If time permits after the MVP demos end-to-end, layer a small learned model on top using the swipe data as labels. Prefer this order; do not invert it.

## The AI interview / personality extraction

- Plan is a **local LLM via Llama** (e.g. Ollama running `llama3.x`). Confirm hardware can run it before committing — if a laptop can't run inference at interview speed, fall back to a hosted API for the demo and keep the local-LLM path behind a config flag.
- The interview's job is to **output the 10-dim trait vector as structured JSON**, not free text. Use a strict system prompt that returns scores 0–1 per trait (the descriptions in `poc.py` are the rubric). Validate/clamp the JSON; never trust the model to stay in range.
- `poc.py` currently loads a BERT model (`AutoTokenizer`/`AutoModel`) but the model name is not yet set and nothing is wired up. BERT-embedding the traits is an *alternative* encoding path — decide early between (a) LLM-scored ordinal traits (simpler, explainable, recommended) and (b) BERT embeddings (denser, harder to interpret and to map onto instruments). Do not build both.

## Data needed

- **Instrument metadata + price history:** use a free market-data source rather than authoring by hand. Options: `yfinance` (Python, no key, easy), Alpha Vantage / Finnhub / Twelve Data (free tiers, need keys). `yfinance` is the fastest path for a demo and covers stocks/ETFs; bonds/CFDs/options will likely need mocked or simplified data.
- **Instrument feature scores** (stability/volatility/reputation sliders): derive volatility from price history (e.g. annualized std of returns); reputation/stability can be heuristic (market cap, sector, beta) or hand-tuned for the demo set. A curated set of **~20–40 instruments** is plenty for a convincing demo — do not try to cover the whole market.
- **Seed personas + their baskets:** hand-author these. This substitutes for the nonexistent "real traders' personality→trade" dataset and powers the "people like you invested in…" feature.
- **No real user PII / no real brokerage/trading.** This is a recommendation/discovery demo, not an executing trading system — keep it that way for scope and safety.

## Tech stack (not yet established — decide and record here once chosen)

Nothing is built yet; the repo contains only notes and a stub. The mobile-app + local-LLM + recommender split suggests:

- **Frontend:** a mobile app (React Native / Expo or Flutter). For a 24h demo, a responsive web app with a swipe UI is a legitimate lighter-weight substitute if mobile tooling slows the team down — prioritize a working demo over native packaging.
- **Backend:** Python (FastAPI) pairs naturally with the ML/data tooling (`transformers`, `yfinance`, `numpy`/`scikit-learn` for similarity) and with Ollama.
- **Model serving:** Ollama for the local Llama interview; scikit-learn / numpy for the similarity recommender (no GPU training needed).

Once the stack is chosen, replace this section with the actual run/build/test commands.

## Current repo state

- `poc.py` — stub: defines the 10 personality traits and imports `transformers`/`torch`. Not runnable end-to-end (no model name, no logic).
- `NOTES.MD` — judging notes and the "Finter" concept.
- `submit.md` — submission email address.
- `.gitignore` — currently ignores `*.md` (note: this means markdown files including notes are untracked; this CLAUDE.md will be untracked too unless the rule is narrowed).

## Conventions

- This is throwaway hackathon code optimized for a 24-hour demo. Favor working vertical slices over polish or generality. When trading off, choose what makes the **live demo** robust.
- Keep secrets (any market-data API keys, etc.) out of git — `.env` + python-dotenv, and add `.env` to `.gitignore` if/when keys are introduced.
