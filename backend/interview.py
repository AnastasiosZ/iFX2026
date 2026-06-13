"""
The AI interview.

A short conversational interview whose ONLY job is to emit the 10-dim trait
vector as strict JSON. Two backends:

  - Ollama (local Llama) if reachable — set FINTER_LLM=ollama and have
    `ollama serve` running with a model (default llama3.1). The interview
    chats for a few turns, then we ask the model to score the traits as JSON.

  - A deterministic keyword/heuristic scorer otherwise (FINTER_LLM=off or
    Ollama unreachable). This keeps the demo fully functional with zero
    external dependencies — the live-demo safety net.

Either way the output is run through sanitize_vector(): unknown keys dropped,
values clamped to [0,1], missing traits set to 0.5. We never trust the model
to stay in range.
"""

from __future__ import annotations

import json
import os
import re

import requests

from .traits import TRAITS, TRAIT_DESCRIPTIONS, sanitize_vector, empty_vector

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
LLM_MODE = os.environ.get("FINTER_LLM", "auto")  # auto | ollama | off

# The interviewer's persona. We keep it to 3-4 questions for a demo.
INTERVIEWER_QUESTIONS = [
    "Tell me about a financial decision you're proud of — what made it feel right?",
    "When an investment moves against you, what actually goes through your head?",
    "Do you trust your own analysis more, or the wisdom of the crowd? Why?",
    "What matters more to you: the chance of a big win, or sleeping soundly at night?",
]

_SCORING_INSTRUCTIONS = (
    "You are a behavioral-finance profiler. Based on the conversation, score the "
    "user on each of the following 10 personality traits from 0.0 (not at all) to "
    "1.0 (extremely). Use the trait descriptions as your rubric. Respond with ONLY "
    "a JSON object mapping each trait name to its score. No prose, no markdown.\n\n"
    "Traits:\n"
    + "\n".join(f"- {t}: {TRAIT_DESCRIPTIONS[t]}" for t in TRAITS)
)


def ollama_available() -> bool:
    if LLM_MODE == "off":
        return False
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def backend_name() -> str:
    return "ollama" if ollama_available() else "heuristic"


def next_question(turn: int) -> str | None:
    """The interviewer question for this turn, or None when the interview is done."""
    if 0 <= turn < len(INTERVIEWER_QUESTIONS):
        return INTERVIEWER_QUESTIONS[turn]
    return None


def score_interview(transcript: list[dict], base_vector: dict[str, float] | None = None) -> dict:
    """
    transcript: [{"q": question, "a": user_answer}, ...].
    Returns {"vector": {...}, "backend": "ollama"|"heuristic"}.
    base_vector (from the questionnaire) is used as the prior the heuristic
    adjusts, and is passed to the LLM as context.
    """
    base = base_vector or empty_vector()
    if ollama_available():
        try:
            vec = _score_with_ollama(transcript, base)
            return {"vector": sanitize_vector(vec), "backend": "ollama"}
        except Exception as e:
            print(f"[interview] ollama scoring failed ({e}); falling back to heuristic.")
    return {"vector": _score_heuristic(transcript, base), "backend": "heuristic"}


def _score_with_ollama(transcript: list[dict], base: dict[str, float]) -> dict:
    convo = "\n".join(
        f"Interviewer: {t.get('q','')}\nUser: {t.get('a','')}" for t in transcript
    )
    prompt = (
        f"{_SCORING_INSTRUCTIONS}\n\n"
        f"Prior estimate (from a questionnaire, adjust as needed): "
        f"{json.dumps({k: round(v,2) for k,v in base.items()})}\n\n"
        f"Conversation:\n{convo}\n\nJSON:"
    )
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",          # ask Ollama to constrain output to JSON
            "options": {"temperature": 0.2},
        },
        timeout=60,
    )
    r.raise_for_status()
    text = r.json().get("response", "")
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response, defensively."""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


# --- Heuristic fallback: keyword cues -> trait nudges on top of the prior ---
# Crude but deterministic and demo-safe. Each (regex -> {trait: delta}).
_CUES: list[tuple[str, dict[str, float]]] = [
    (r"\b(hold|long term|long-term|patient|wait|years)\b", {"patience": 0.2, "discipline": 0.15, "impulsivity": -0.15}),
    (r"\b(sell|panic|cut|scared|nervous|anxious|worried)\b", {"risk_aversion": 0.2, "impulsivity": 0.15, "risk_tolerance": -0.15}),
    (r"\b(research|analy|numbers|data|fundamentals|charts|dd)\b", {"analytical_depth": 0.25, "discipline": 0.1}),
    (r"\b(gut|feeling|instinct|vibe)\b", {"impulsivity": 0.2, "analytical_depth": -0.2, "confidence": 0.1}),
    (r"\b(crowd|everyone|popular|trend|following|hype)\b", {"herd_mentality": 0.25, "contrarian_tendency": -0.15}),
    (r"\b(against|contrarian|opposite|nobody|unpopular|blood)\b", {"contrarian_tendency": 0.25, "herd_mentality": -0.2}),
    (r"\b(big win|moon|10x|huge|massive|fortune|rich)\b", {"greed": 0.25, "risk_tolerance": 0.2, "discipline": -0.1}),
    (r"\b(safe|sleep|stable|preserve|protect|secure|cautious)\b", {"risk_aversion": 0.25, "patience": 0.1, "risk_tolerance": -0.15}),
    (r"\b(confident|sure|certain|conviction|believe)\b", {"confidence": 0.2}),
    (r"\b(plan|rule|stick|discipline|stop loss|stop-loss)\b", {"discipline": 0.25, "impulsivity": -0.15}),
    (r"\b(quick|fast|immediately|now|jump)\b", {"impulsivity": 0.2, "patience": -0.15}),
    (r"\b(risk|aggressive|bold|all in|all-in|yolo)\b", {"risk_tolerance": 0.25, "greed": 0.15, "risk_aversion": -0.2}),
]


def _score_heuristic(transcript: list[dict], base: dict[str, float]) -> dict[str, float]:
    vec = dict(base)
    text = " ".join(t.get("a", "") for t in transcript).lower()
    for pattern, deltas in _CUES:
        if re.search(pattern, text):
            for trait, d in deltas.items():
                if trait in vec:
                    vec[trait] += d
    return sanitize_vector(vec)
