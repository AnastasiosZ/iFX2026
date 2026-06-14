"""
Finter FastAPI backend.

Endpoints (all JSON unless noted):
  GET  /                      -> serves the web app (frontend/index.html)
  GET  /api/health            -> status + which LLM backend is live

  -- accounts --
  POST /api/auth/signup       -> create account (password hashed+salted) -> session
  POST /api/auth/login        -> authenticate -> session (+ triggers data refresh)
  POST /api/auth/logout       -> end a session

  -- onboarding --
  GET  /api/questions         -> onboarding multiple-choice questionnaire
  POST /api/session           -> apply quiz answers to the logged-in user
  GET  /api/interview/next    -> next interview question for a session
  POST /api/interview         -> submit transcript, score traits, finalize vector

  -- scenario refinement (second stage) --
  GET  /api/scenarios         -> story-driven scenarios that sharpen the profile
  POST /api/scenarios         -> apply scenario answers -> updated vector + persona

  -- discovery --
  GET  /api/recommend         -> ranked recommendations (optional ?asset_class=)
  POST /api/swipe             -> record a like/pass, returns updated profile
  GET  /api/instrument/{sym}  -> full detail for one instrument (strategy + metadata)
  GET  /api/profile           -> a session's current effective trait vector + personas
  GET  /api/asset_classes     -> the section tabs the UI should render

A "session" is a logged-in user: the session_id is the auth token, mapped in
memory to that user's live state. The personality vector and likes are persisted
to SQLite (see db.py) so they survive restarts; the in-memory state just holds
the live swipe-decay during a browsing session.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import recommender, interview, db, auth, questionnaire, scenarios as scenarios_mod
from .build_instruments import build, OUT_PATH
from .questionnaire import score_answers
from .scenarios import apply_scenarios
from .traits import sanitize_vector, empty_vector, TRAIT_DESCRIPTIONS

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# Daily swipe budget. A user gets this many swipes per (UTC) day; the counter
# ticks down as they burn through cards and resets the next day (req #17).
DAILY_SWIPE_LIMIT = 20

app = FastAPI(title="Finter API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- In-memory session store: token -> recommender.UserState ---
SESSIONS: dict[str, recommender.UserState] = {}

# Serialize instrument rebuilds so a login burst can't launch many at once.
_rebuild_lock = threading.Lock()


def _load_instruments() -> list[dict]:
    """Load cached instruments.json, building it on first run if missing."""
    if not OUT_PATH.exists():
        print("[app] instruments.json missing; building it now...")
        return build()
    with open(OUT_PATH, encoding="utf-8") as f:
        return json.load(f)["instruments"]


def _rebuild_instruments(reason: str) -> None:
    """(Re)pull live market data and hot-swap it into the recommender."""
    if not _rebuild_lock.acquire(blocking=False):
        return  # a rebuild is already running; skip this trigger
    try:
        print(f"[app] rebuilding instruments ({reason})...")
        instruments = build()
        recommender.load(instruments)
        print(f"[app] instruments refreshed: {len(instruments)}")
    except Exception as e:
        print(f"[app] instrument rebuild failed ({e}); keeping previous data.")
    finally:
        _rebuild_lock.release()


def _today() -> str:
    """Current UTC date as YYYY-MM-DD — the key for the daily swipe counter."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    instruments = _load_instruments()
    recommender.load(instruments)
    # Instrument data is (re)built on each login only (req #16); no periodic refresh.
    print(f"[app] loaded {len(instruments)} instruments; LLM backend: {interview.backend_name()}")


# ---------------------------------------------------------------- models
class SignupIn(BaseModel):
    username: str
    email: str = ""
    password: str


class LoginIn(BaseModel):
    username: str
    password: str


class LogoutIn(BaseModel):
    session_id: str


class SessionAnswers(BaseModel):
    session_id: str
    answers: dict[str, int] = {}  # question_id -> option_index


class InterviewSubmit(BaseModel):
    session_id: str
    transcript: list[dict] = []   # [{"q":..., "a":...}]


class ScenarioSubmit(BaseModel):
    session_id: str
    answers: dict[str, int] = {}  # scenario_id -> option_index


class SwipeIn(BaseModel):
    session_id: str
    symbol: str
    liked: bool


def _require_session(session_id: str) -> recommender.UserState:
    state = SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=401, detail="Not logged in / unknown session")
    return state


def _persona_for(state: recommender.UserState) -> str | None:
    """The persona used for the same-persona crowd signal: assigned, else nearest."""
    if state.persona_id:
        return state.persona_id
    near = recommender.nearest_personas(state.effective_vector(), k=1)
    return near[0]["id"] if near else None


def _persist_profile(state: recommender.UserState) -> None:
    if state.user_id is not None:
        db.update_user_profile(state.user_id, state.base_vector, state.persona_id)


# ---------------------------------------------------------------- accounts
@app.post("/api/auth/signup")
def signup(body: SignupIn):
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="Username already taken")
    user = db.create_user(username, body.email.strip(), body.password)
    token = auth.new_token()
    SESSIONS[token] = recommender.UserState(
        base_vector=empty_vector(), user_id=user["id"], persona_id=None,
    )
    return {"session_id": token, "username": username, "has_profile": False}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = db.get_user_by_username(body.username.strip())
    if not user or not auth.verify_password(body.password, user["salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    base = user["base_vector"] or empty_vector()
    state = recommender.UserState(
        base_vector=base, user_id=user["id"], persona_id=user["persona_id"],
    )
    # Replay persisted likes so they're filtered out of the deck, with an old
    # timestamp so they barely nudge the live vector (history already shaped it).
    old_ts = time.time() - 7 * recommender.SWIPE_HALFLIFE_S
    for sym in db.get_user_likes(user["id"]):
        state.swipes.append(recommender.Swipe(symbol=sym, liked=True, ts=old_ts))

    token = auth.new_token()
    SESSIONS[token] = state

    # req: rebuild live instrument data every time a user logs in (non-blocking).
    threading.Thread(target=_rebuild_instruments, args=("user login",), daemon=True).start()

    has_profile = user["base_vector"] is not None and user["persona_id"] is not None
    return {
        "session_id": token,
        "username": user["username"],
        "has_profile": has_profile,
        "vector": state.effective_vector(),
        "personas": recommender.nearest_personas(state.effective_vector()),
    }


@app.post("/api/auth/logout")
def logout(body: LogoutIn):
    SESSIONS.pop(body.session_id, None)
    return {"ok": True}


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
    """A fresh, randomly-chosen subset of the predefined onboarding questions."""
    return {"questions": questionnaire.to_public(questionnaire.random_pool(8))}


@app.get("/api/scenarios")
def scenarios():
    """A fresh, randomly-chosen handful of the 20 predefined Quizzes-tab scenarios."""
    return {"scenarios": scenarios_mod.to_public(scenarios_mod.random_pool())}


@app.get("/api/asset_classes")
def asset_classes():
    order = ["stock", "etf", "bond", "crypto", "cfd"]
    present = {i["asset_class"] for i in recommender.INSTRUMENTS}
    labels = {"stock": "Stocks", "etf": "ETFs", "bond": "Bonds", "crypto": "Crypto", "cfd": "CFDs"}
    return {"asset_classes": [
        {"id": a, "label": labels.get(a, a.title())} for a in order if a in present
    ]}


@app.post("/api/session")
def apply_questionnaire(body: SessionAnswers):
    """Apply onboarding quiz answers to the logged-in user's profile."""
    state = _require_session(body.session_id)
    state.base_vector = score_answers(body.answers)
    _persist_profile(state)
    return {"session_id": body.session_id, "base_vector": state.base_vector}


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
    near = recommender.nearest_personas(state.base_vector)
    state.persona_id = near[0]["id"] if near else None
    _persist_profile(state)
    # Stamp the re-evaluation gate: completing the interview counts as a full
    # trait evaluation, and the user may only run one per day (req #18).
    if state.user_id is not None:
        db.set_last_eval_day(state.user_id, _today())
    return {
        "vector": state.base_vector,
        "backend": result["backend"],
        "personas": near,
    }


@app.post("/api/scenarios")
def submit_scenarios(body: ScenarioSubmit):
    """Refine the profile with scenario answers (applied on top of current vector)."""
    state = _require_session(body.session_id)
    state.base_vector = apply_scenarios(state.base_vector, body.answers)
    near = recommender.nearest_personas(state.base_vector)
    state.persona_id = near[0]["id"] if near else None
    _persist_profile(state)
    return {
        "vector": state.base_vector,
        "effective_vector": state.effective_vector(),
        "personas": near,
    }


@app.get("/api/recommend")
def recommend(session_id: str, asset_class: str | None = Query(default=None), limit: int = 20):
    state = _require_session(session_id)
    persona_id = _persona_for(state)
    crowd = db.likes_by_persona(persona_id, exclude_user_id=state.user_id)
    items = recommender.recommend(
        state, asset_class=asset_class, limit=limit, persona_like_counts=crowd,
    )
    if state.user_id is not None and items:
        db.log_recommendations(state.user_id, items)
    return {
        "items": items,
        "effective_vector": state.effective_vector(),
        "swipes_remaining": _swipes_remaining(state),
        "daily_swipe_limit": DAILY_SWIPE_LIMIT,
    }


def _swipes_remaining(state: recommender.UserState) -> int:
    """How many swipes the user has left today (req #17). Unlimited for anon."""
    if state.user_id is None:
        return DAILY_SWIPE_LIMIT
    used = db.get_swipe_count_today(state.user_id, _today())
    return max(DAILY_SWIPE_LIMIT - used, 0)


@app.post("/api/swipe")
def swipe(body: SwipeIn):
    state = _require_session(body.session_id)
    if body.symbol not in recommender.INSTRUMENTS_BY_SYMBOL:
        raise HTTPException(status_code=400, detail="Unknown symbol")

    # Enforce the daily swipe budget before recording anything.
    if state.user_id is not None and _swipes_remaining(state) <= 0:
        raise HTTPException(
            status_code=429,
            detail="You've used all your swipes for today. Come back tomorrow!",
        )

    now = time.time()
    state.swipes.append(recommender.Swipe(symbol=body.symbol, liked=body.liked, ts=now))

    # Persist the swipe's effect on the personality. effective_vector() folds the
    # decayed swipe nudges onto the base vector; we snapshot that, promote it to
    # the new base_vector and write it to the DB, so the personalization survives
    # logout/login instead of living only in this process's memory. We then age
    # the swipe list (its nudges are now baked into base) so the SAME nudges are
    # not re-applied on top of the updated base on the next recompute — the
    # swipes remain only as 'already seen' markers for deck filtering.
    eff = state.effective_vector()
    state.base_vector = eff
    aged_ts = now - 7 * recommender.SWIPE_HALFLIFE_S
    for s in state.swipes:
        s.ts = aged_ts
    near = recommender.nearest_personas(eff)
    state.persona_id = near[0]["id"] if near else state.persona_id

    if state.user_id is not None:
        db.increment_swipe_count(state.user_id, _today())
        if body.liked:
            db.add_like(state.user_id, body.symbol)
        else:
            db.remove_like(state.user_id, body.symbol)
        _persist_profile(state)
    return {
        "ok": True,
        "n_swipes": len(state.swipes),
        "swipes_remaining": _swipes_remaining(state),
        "effective_vector": eff,
        "personas": near,
    }


class WatchlistRemoveIn(BaseModel):
    session_id: str
    symbol: str


@app.get("/api/watchlist")
def watchlist(session_id: str):
    """
    The user's liked instruments, scored against their CURRENT profile so the UI
    can sort them highest-match first and filter by asset class (req #21). Each
    item carries its asset_class, match % and the personalized 'why'.
    """
    state = _require_session(session_id)
    if state.user_id is None:
        return {"items": []}
    liked = set(db.get_user_likes(state.user_id))
    if not liked:
        return {"items": []}
    persona_id = _persona_for(state)
    crowd = db.likes_by_persona(persona_id, exclude_user_id=state.user_id)
    scored = recommender.recommend(
        state, asset_class=None, limit=len(recommender.INSTRUMENTS),
        persona_like_counts=crowd,
    )
    items = [it for it in scored if it["symbol"] in liked]
    items.sort(key=lambda r: r["match"], reverse=True)
    return {"items": items}


@app.post("/api/watchlist/remove")
def watchlist_remove(body: WatchlistRemoveIn):
    """
    Remove an instrument from the watchlist. This drops the persisted like AND
    the in-session 'liked' swipe, so the user's effective trait vector is no
    longer nudged toward it and the instrument can reappear in Discover
    (reqs #10 & #15).
    """
    state = _require_session(body.session_id)
    if state.user_id is not None:
        db.remove_like(state.user_id, body.symbol)

    # The like's nudge is baked into the persisted base_vector, so it can't be
    # undone just by dropping the in-memory swipe. Apply a reverse ('pass') nudge
    # to walk the personality back, bake that into base, persist it, then drop all
    # swipes for this symbol so it can resurface in Discover (reqs #10 & #15).
    if body.symbol in recommender.INSTRUMENTS_BY_SYMBOL:
        now = time.time()
        state.swipes.append(recommender.Swipe(symbol=body.symbol, liked=False, ts=now))
        state.base_vector = state.effective_vector()
    state.swipes = [s for s in state.swipes if s.symbol != body.symbol]
    aged_ts = time.time() - 7 * recommender.SWIPE_HALFLIFE_S
    for s in state.swipes:
        s.ts = aged_ts
    near = recommender.nearest_personas(state.base_vector)
    state.persona_id = near[0]["id"] if near else state.persona_id
    _persist_profile(state)
    return {
        "ok": True,
        "effective_vector": state.effective_vector(),
        "personas": near,
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
    can_reevaluate = True
    if state.user_id is not None:
        can_reevaluate = db.get_last_eval_day(state.user_id) != _today()
    return {
        "base_vector": state.base_vector,
        "effective_vector": eff,
        "trait_descriptions": TRAIT_DESCRIPTIONS,
        "personas": recommender.nearest_personas(eff),
        "n_swipes": len(state.swipes),
        "swipes_remaining": _swipes_remaining(state),
        "daily_swipe_limit": DAILY_SWIPE_LIMIT,
        "can_reevaluate": can_reevaluate,
    }


class DeleteAccountIn(BaseModel):
    session_id: str


@app.post("/api/auth/delete")
def delete_account(body: DeleteAccountIn):
    """Permanently delete the logged-in user and all their data (req #22)."""
    state = _require_session(body.session_id)
    if state.user_id is not None:
        db.delete_user(state.user_id)
    SESSIONS.pop(body.session_id, None)
    return {"ok": True}


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