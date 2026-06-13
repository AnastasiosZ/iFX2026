"""
Finter FastAPI backend.

Endpoints (all JSON unless noted):
  GET  /                      -> serves the web app (frontend/index.html)
  GET  /api/health            -> status + which LLM backend is live
  GET  /api/questions         -> onboarding multiple-choice questionnaire
  POST /api/session           -> create a session from questionnaire answers
  GET  /api/interview/next    -> next interview question for a session
  POST /api/interview         -> submit transcript, score traits, finalize vector
  GET  /api/recommend         -> ranked recommendations (optional ?asset_class=)
  POST /api/swipe             -> record a like/pass, returns updated profile
  GET  /api/instrument/{sym}  -> full detail for one instrument
  GET  /api/profile           -> a session's current effective trait vector + personas
  GET  /api/asset_classes     -> the section tabs the UI should render

Sessions are in-memory (a dict). Fine for a hackathon demo; not for production.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import recommender, interview
from .build_instruments import build, OUT_PATH
from .questionnaire import public_questions, score_answers
from .traits import sanitize_vector, empty_vector, TRAIT_DESCRIPTIONS

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="Finter API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- In-memory session store: session_id -> recommender.UserState ---
SESSIONS: dict[str, recommender.UserState] = {}


def _load_instruments() -> list[dict]:
    """Load cached instruments.json, building it on first run if missing."""
    if not OUT_PATH.exists():
        print("[app] instruments.json missing; building it now...")
        return build()
    with open(OUT_PATH, encoding="utf-8") as f:
        return json.load(f)["instruments"]


@app.on_event("startup")
def _startup() -> None:
    instruments = _load_instruments()
    recommender.load(instruments)
    print(f"[app] loaded {len(instruments)} instruments; LLM backend: {interview.backend_name()}")


# ---------------------------------------------------------------- models
class SessionCreate(BaseModel):
    answers: dict[str, int] = {}  # question_id -> option_index


class InterviewSubmit(BaseModel):
    session_id: str
    transcript: list[dict] = []   # [{"q":..., "a":...}]


class SwipeIn(BaseModel):
    session_id: str
    symbol: str
    liked: bool


def _require_session(session_id: str) -> recommender.UserState:
    state = SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown session_id")
    return state


# ---------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_backend": interview.backend_name(),
        "instruments": len(recommender.INSTRUMENTS),
        "sessions": len(SESSIONS),
    }


@app.get("/api/questions")
def questions():
    return {"questions": public_questions()}


@app.get("/api/asset_classes")
def asset_classes():
    order = ["stock", "etf", "bond", "crypto", "cfd"]
    present = {i["asset_class"] for i in recommender.INSTRUMENTS}
    labels = {"stock": "Stocks", "etf": "ETFs", "bond": "Bonds", "crypto": "Crypto", "cfd": "CFDs"}
    return {"asset_classes": [
        {"id": a, "label": labels.get(a, a.title())} for a in order if a in present
    ]}


@app.post("/api/session")
def create_session(body: SessionCreate):
    base = score_answers(body.answers)
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = recommender.UserState(base_vector=base)
    return {"session_id": sid, "base_vector": base}


@app.get("/api/interview/next")
def interview_next(session_id: str, turn: int = 0):
    _require_session(session_id)
    q = interview.next_question(turn)
    return {"question": q, "done": q is None, "turn": turn}


@app.post("/api/interview")
def submit_interview(body: InterviewSubmit):
    state = _require_session(body.session_id)
    result = interview.score_interview(body.transcript, state.base_vector)
    # Blend interview result over the questionnaire prior (interview gets more weight).
    blended = {}
    for t in result["vector"]:
        blended[t] = 0.4 * state.base_vector.get(t, 0.5) + 0.6 * result["vector"][t]
    state.base_vector = sanitize_vector(blended)
    return {
        "vector": state.base_vector,
        "backend": result["backend"],
        "personas": recommender.nearest_personas(state.base_vector),
    }


@app.get("/api/recommend")
def recommend(session_id: str, asset_class: str | None = Query(default=None), limit: int = 20):
    state = _require_session(session_id)
    items = recommender.recommend(state, asset_class=asset_class, limit=limit)
    return {"items": items, "effective_vector": state.effective_vector()}


@app.post("/api/swipe")
def swipe(body: SwipeIn):
    state = _require_session(body.session_id)
    if body.symbol not in recommender.INSTRUMENTS_BY_SYMBOL:
        raise HTTPException(status_code=400, detail="Unknown symbol")
    state.swipes.append(recommender.Swipe(symbol=body.symbol, liked=body.liked))
    return {
        "ok": True,
        "n_swipes": len(state.swipes),
        "effective_vector": state.effective_vector(),
        "personas": recommender.nearest_personas(state.effective_vector()),
    }


@app.get("/api/instrument/{symbol}")
def instrument(symbol: str):
    inst = recommender.INSTRUMENTS_BY_SYMBOL.get(symbol)
    if inst is None:
        raise HTTPException(status_code=404, detail="Unknown symbol")
    return inst


@app.get("/api/profile")
def profile(session_id: str):
    state = _require_session(session_id)
    eff = state.effective_vector()
    return {
        "base_vector": state.base_vector,
        "effective_vector": eff,
        "trait_descriptions": TRAIT_DESCRIPTIONS,
        "personas": recommender.nearest_personas(eff),
        "n_swipes": len(state.swipes),
    }


# ---------------------------------------------------------------- static frontend
@app.get("/")
def index():
    idx = FRONTEND / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"detail": "frontend not built"}, status_code=404)


# Serve the rest of the frontend (app.js, style.css) under /static.
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
