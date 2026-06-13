/* Finter front-end. Vanilla JS, no build step.
   Flow: welcome -> questionnaire -> AI interview -> profile reveal -> swipe deck.
   Talks to the FastAPI backend on the same origin. */

const API = "";  // same origin
const S = {
  sessionId: null,
  username: null,
  answers: {},
  quizIdx: 0,
  questions: [],
  interviewTurn: 0,
  transcript: [],
  assetClasses: [],
  activeClass: null,
  deck: [],        // current asset-class recommendations queue
  likes: [],       // {symbol,name,match,why}
  personas: [],
  seen: {},        // symbol -> full recommend item (carries why + strategy)
  scenarios: [],
  scenarioIdx: 0,
  scenarioAnswers: {},
  swipesRemaining: null,   // daily swipe budget left (null until known)
  dailyLimit: 20,
  canReevaluate: true,
  interviewBusy: false,    // lock while the AI is "thinking" (anti-spam)
  watchlist: [],           // full watchlist items from the backend
  watchlistFilter: "all",  // active asset-class filter on the watchlist tab
};

const $ = (id) => document.getElementById(id);
const api = async (path, opts) => {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
};

function show(screenId) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(screenId).classList.add("active");
  // sync bottom nav
  document.querySelectorAll("#bottomnav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.screen === screenId)
  );
}

/* ---------------- boot ---------------- */
window.addEventListener("DOMContentLoaded", async () => {
  $("start-btn").onclick = () => show("screen-signup");
  $("signup-back-to-welcome").onclick = () => show("screen-welcome");
  $("signup-submit-btn").onclick = doSignup;
  $("to-deck-btn").onclick = () => { show("screen-deck"); $("bottomnav").classList.remove("hidden"); };
  $("back-to-deck").onclick = () => show("screen-deck");
  $("chat-send").onclick = sendChat;
  $("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
  $("modal-close").onclick = () => $("modal").classList.add("hidden");
  $("btn-like").onclick = () => swipeTop(true);
  $("btn-pass").onclick = () => swipeTop(false);
  $("btn-info").onclick = () => { const t = topCard(); if (t) openModal(t.dataset.symbol); };
  $("logout-btn").onclick = doLogout;
  $("reevaluate-btn").onclick = doReevaluate;
  $("delete-account-btn").onclick = doDeleteAccount;
  $("scenario-finish").onclick = () => show("screen-deck");
  document.querySelectorAll("#bottomnav button").forEach((b) => {
    b.onclick = () => {
      const target = b.dataset.screen;
      if (target === "screen-likes") return loadWatchlist();
      if (target === "screen-scenarios") return startScenarios();
      show(target);
      if (target === "screen-profile") refreshProfile();
    };
  });

  $("login-btn").onclick = () => show("screen-login");
  $("back-to-welcome").onclick = () => show("screen-welcome");
  $("login-submit-btn").onclick = doLogin;
  $("login-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
});

/* ---------------- auth ---------------- */
async function doSignup() {
  const user = $("signup-username").value.trim();
  const email = $("signup-email").value.trim();
  const pass = $("signup-password").value;
  const confirm = $("signup-confirm").value;
  if (!user || !email || !pass) { alert("Please fill in username, email and password."); return; }
  if (pass !== confirm) { alert("Passwords don't match"); return; }
  try {
    const res = await api("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ username: user, email, password: pass }),
    });
    S.sessionId = res.session_id;
    S.username = res.username;
    beginQuiz();
  } catch (e) {
    alert("Could not create account — that username may be taken.");
  }
}

async function doLogin() {
  const user = $("login-username").value.trim();
  const pass = $("login-password").value;
  if (!user || !pass) return;
  try {
    const res = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: user, password: pass }),
    });
    S.sessionId = res.session_id;
    S.username = res.username;
    if (res.has_profile) {
      // Returning user — skip onboarding, go straight to the deck.
      S.personas = res.personas; S.vector = res.vector;
      await loadTabs();
      await loadDeck();
      show("screen-deck");
      $("bottomnav").classList.remove("hidden");
    } else {
      beginQuiz();
    }
  } catch (e) {
    alert("Invalid username or password.");
  }
}

async function doLogout() {
  try { await api("/api/auth/logout", { method: "POST", body: JSON.stringify({ session_id: S.sessionId }) }); } catch {}
  // reset client state
  S.sessionId = null; S.username = null; S.answers = {}; S.quizIdx = 0;
  S.transcript = []; S.deck = []; S.likes = []; S.personas = []; S.seen = {};
  S.scenarioAnswers = {}; S.scenarioIdx = 0;
  S.watchlist = []; S.watchlistFilter = "all"; S.swipesRemaining = null; S._pendingQ = null;
  $("like-count").textContent = "0";
  $("bottomnav").classList.add("hidden");
  $("login-username").value = ""; $("login-password").value = "";
  show("screen-welcome");
}

/* ---------------- questionnaire ---------------- */
async function beginQuiz() {
  const { questions } = await api("/api/questions");
  S.questions = questions;
  S.quizIdx = 0;
  show("screen-quiz");
  renderQuiz();
}

function renderQuiz() {
  const q = S.questions[S.quizIdx];
  $("quiz-progress").style.width = `${(S.quizIdx / S.questions.length) * 100}%`;
  const body = $("quiz-body");
  body.innerHTML = `<div class="q-prompt">${q.prompt}</div>`;
  q.options.forEach((opt, i) => {
    const el = document.createElement("div");
    el.className = "q-opt";
    el.textContent = opt.label;
    el.onclick = () => {
      S.answers[q.id] = i;
      el.classList.add("sel");
      setTimeout(nextQuiz, 180);
    };
    body.appendChild(el);
  });
}

async function nextQuiz() {
  S.quizIdx++;
  if (S.quizIdx < S.questions.length) {
    renderQuiz();
  } else {
    $("quiz-progress").style.width = "100%";
    // apply quiz answers to the logged-in user's profile
    await api("/api/session", {
      method: "POST",
      body: JSON.stringify({ session_id: S.sessionId, answers: S.answers }),
    });
    startInterview();
  }
}

/* ---------------- interview ---------------- */
// Lock the input while the AI is "thinking" so spamming Enter can't queue
// multiple answers or make two questions appear at once (req #20).
function setInterviewBusy(busy) {
  S.interviewBusy = busy;
  $("chat-input").disabled = busy;
  $("chat-send").disabled = busy;
  if (!busy) $("chat-input").focus();
}

async function startInterview() {
  show("screen-interview");
  $("chat").innerHTML = "";
  S.interviewTurn = 0;
  S.transcript = [];
  S._pendingQ = null;
  addBubble("ai", "Hey! I'm your Finter guide. A few quick questions so I really get you 👇");
  await askNext();
}

async function askNext() {
  setInterviewBusy(true);                 // no answering until the question is up
  const typing = addBubble("ai", "…");
  typing.classList.add("typing");
  let data;
  try {
    data = await api(`/api/interview/next?session_id=${S.sessionId}&turn=${S.interviewTurn}`);
  } catch {
    typing.remove();
    setInterviewBusy(false);
    return;
  }
  typing.remove();
  if (data.done || !data.question) return finishInterview();
  addBubble("ai", data.question);
  S._pendingQ = data.question;            // only now is an answer accepted
  setInterviewBusy(false);
}

function addBubble(who, text) {
  const b = document.createElement("div");
  b.className = `bubble ${who}`;
  b.textContent = text;
  $("chat").appendChild(b);
  $("chat").scrollTop = $("chat").scrollHeight;
  return b;
}

async function sendChat() {
  if (S.interviewBusy) return;            // AI is still responding — ignore spam
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text || !S._pendingQ) return;
  input.value = "";
  addBubble("me", text);
  S.transcript.push({ q: S._pendingQ, a: text });
  S._pendingQ = null;
  S.interviewTurn++;
  await askNext();
}

async function finishInterview() {
  const typing = addBubble("ai", "Analyzing your trader DNA…");
  typing.classList.add("typing");
  const res = await api("/api/interview", {
    method: "POST",
    body: JSON.stringify({ session_id: S.sessionId, transcript: S.transcript }),
  });
  S.personas = res.personas;
  S.vector = res.vector;
  S.canReevaluate = false;   // completing the interview uses today's re-eval slot
  typing.remove();
  setTimeout(() => revealProfile(), 300);
}

/* ---------------- profile ---------------- */
function revealProfile() {
  show("screen-profile");
  updateReevaluateBtn();
  renderPersonas(S.personas);
  drawRadar(S.vector);
}

async function refreshProfile() {
  try {
    const p = await api(`/api/profile?session_id=${S.sessionId}`);
    S.personas = p.personas; S.vector = p.effective_vector;
    S.canReevaluate = p.can_reevaluate !== false;
    if (p.swipes_remaining != null) S.swipesRemaining = p.swipes_remaining;
    renderPersonas(p.personas);
    drawRadar(p.effective_vector);
    updateReevaluateBtn();
  } catch {}
}

function updateReevaluateBtn() {
  const btn = $("reevaluate-btn");
  btn.disabled = !S.canReevaluate;
  btn.textContent = S.canReevaluate
    ? "Re-evaluate my traits"
    : "Re-evaluation available tomorrow";
}

async function doReevaluate() {
  if (!S.canReevaluate) return;
  const ok = confirm(
    "Re-evaluate your trader DNA?\n\nThis restarts the questionnaire and AI interview and replaces your current profile. You can only do this once per day."
  );
  if (!ok) return;
  // Reset onboarding state and run the full flow again.
  S.answers = {}; S.quizIdx = 0; S.transcript = []; S.interviewTurn = 0; S._pendingQ = null;
  $("bottomnav").classList.add("hidden");
  beginQuiz();
}

async function doDeleteAccount() {
  const ok = confirm(
    "Delete your account?\n\nThis permanently erases your profile, watchlist and history. This cannot be undone."
  );
  if (!ok) return;
  try {
    await api("/api/auth/delete", {
      method: "POST",
      body: JSON.stringify({ session_id: S.sessionId }),
    });
  } catch {}
  alert("Your account has been deleted.");
  doLogout();
}

function renderPersonas(personas) {
  const wrap = $("persona-cards");
  wrap.innerHTML = "";
  personas.slice(0, 3).forEach((p) => {
    const el = document.createElement("div");
    el.className = "persona";
    el.innerHTML = `
      <div class="ring" style="--p:${p.match}"><span>${p.match}%</span></div>
      <div class="meta"><b>${p.name}</b><p>${p.blurb}</p></div>`;
    wrap.appendChild(el);
  });
}

const TRAIT_ORDER = ["risk_tolerance","risk_aversion","patience","impulsivity","discipline","greed","confidence","analytical_depth","contrarian_tendency","herd_mentality"];
// Full, readable trait labels for the radar (no 8-char truncation — req #4).
const TRAIT_SHORT = { risk_tolerance:"Risk Appetite", risk_aversion:"Caution", patience:"Patience", impulsivity:"Impulsiveness", discipline:"Discipline", greed:"Greed", confidence:"Confidence", analytical_depth:"Analytical", contrarian_tendency:"Contrarian", herd_mentality:"Herd Instinct" };

function drawRadar(vec) {
  const c = $("radar"); const ctx = c.getContext("2d");
  const W = c.width, H = c.height, cx = W/2, cy = H/2, R = 100;
  const n = TRAIT_ORDER.length;
  ctx.clearRect(0,0,W,H);
  // grid
  ctx.strokeStyle = "#ffffff22"; ctx.fillStyle = "#9aa0bd"; ctx.font = "10px sans-serif"; ctx.textBaseline = "middle";
  for (let ring=1; ring<=3; ring++) {
    ctx.beginPath();
    for (let i=0;i<=n;i++){ const a=(i/n)*Math.PI*2 - Math.PI/2; const r=R*ring/3; const x=cx+r*Math.cos(a), y=cy+r*Math.sin(a); i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.stroke();
  }
  // axes + labels (full trait names; align text away from the edges so nothing clips)
  for (let i=0;i<n;i++){ const a=(i/n)*Math.PI*2 - Math.PI/2;
    ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(cx+R*Math.cos(a), cy+R*Math.sin(a)); ctx.stroke();
    const cosA = Math.cos(a);
    const lx=cx+(R+14)*cosA, ly=cy+(R+14)*Math.sin(a);
    ctx.textAlign = cosA > 0.25 ? "left" : cosA < -0.25 ? "right" : "center";
    ctx.fillText(TRAIT_SHORT[TRAIT_ORDER[i]], lx, ly);
  }
  // polygon
  ctx.beginPath();
  TRAIT_ORDER.forEach((t,i)=>{ const a=(i/n)*Math.PI*2 - Math.PI/2; const v=vec[t]??0.5; const r=R*v; const x=cx+r*Math.cos(a), y=cy+r*Math.sin(a); i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
  ctx.closePath();
  ctx.fillStyle = "rgba(255,90,126,0.35)"; ctx.strokeStyle = "#ff5a7e"; ctx.lineWidth=2; ctx.fill(); ctx.stroke();
}

/* ---------------- deck ---------------- */
async function loadTabs() {
  const { asset_classes } = await api("/api/asset_classes");
  S.assetClasses = asset_classes;
  S.activeClass = asset_classes[0]?.id || null;
  const tabs = $("tabs"); tabs.innerHTML = "";
  asset_classes.forEach((a) => {
    const b = document.createElement("button");
    b.textContent = a.label;
    b.classList.toggle("active", a.id === S.activeClass);
    b.onclick = () => { S.activeClass = a.id; [...tabs.children].forEach(c=>c.classList.remove("active")); b.classList.add("active"); loadDeck(); };
    tabs.appendChild(b);
  });
}

async function loadDeck() {
  const res = await api(`/api/recommend?session_id=${S.sessionId}&asset_class=${S.activeClass}&limit=40`);
  S.deck = res.items.filter((i) => !i.already_swiped);
  res.items.forEach((i) => { S.seen[i.symbol] = i; });  // keep why + strategy for the modal
  if (res.swipes_remaining != null) S.swipesRemaining = res.swipes_remaining;
  if (res.daily_swipe_limit != null) S.dailyLimit = res.daily_swipe_limit;
  renderDeck();
  updateMatchStrip();
  updateSwipeMeter();
}

function updateSwipeMeter() {
  const meter = $("swipe-meter");
  if (S.swipesRemaining == null) { meter.classList.add("hidden"); return; }
  meter.classList.remove("hidden");
  const n = S.swipesRemaining;
  meter.textContent = n > 0
    ? `⚡ ${n} swipe${n === 1 ? "" : "s"} left today`
    : "⚡ No swipes left today — come back tomorrow!";
  meter.classList.toggle("empty", n <= 0);
}

function swipesExhausted() {
  return S.swipesRemaining != null && S.swipesRemaining <= 0;
}

function updateMatchStrip() {
  const top = S.personas[0];
  $("match-strip").innerHTML = top
    ? `Showing picks loved by <b>${top.name}</b> types and people who match your profile`
    : "";
}

function renderDeck() {
  const deck = $("deck");
  deck.innerHTML = "";
  if (swipesExhausted()) {
    $("swipe-controls").classList.add("hidden");   // remove the buttons entirely
    deck.innerHTML = `<div class="deck-empty">⚡<br/>You're out of swipes for today.<br/>Come back tomorrow for a fresh batch of picks.</div>`;
    return;
  }
  $("swipe-controls").classList.remove("hidden");
  if (!S.deck.length) {
    deck.innerHTML = `<div class="deck-empty">🎉<br/>You've seen every ${labelFor(S.activeClass)} pick.<br/>Try another tab or check your watchlist.</div>`;
    return;
  }
  // render up to 3 stacked (top last so it's on top)
  const slice = S.deck.slice(0, 3).reverse();
  slice.forEach((item, idxFromBack) => {
    const isTop = idxFromBack === slice.length - 1;
    const card = buildCard(item);
    const depth = slice.length - 1 - idxFromBack;
    card.style.transform = `scale(${1 - depth*0.04}) translateY(${depth*10}px)`;
    card.style.zIndex = idxFromBack;
    if (isTop) attachDrag(card, item);
    deck.appendChild(card);
  });
}

function labelFor(id){ return S.assetClasses.find(a=>a.id===id)?.label || id; }

function buildCard(item) {
  const card = document.createElement("div");
  card.className = "card";
  card.dataset.symbol = item.symbol;
  const ret = (item.period_return*100).toFixed(1);
  const retCls = item.period_return >= 0 ? "pos" : "neg";
  card.innerHTML = `
    <div class="stamp like">LIKE</div>
    <div class="stamp nope">NOPE</div>
    <div class="card-top">
      <div>
        <div class="sym">${item.symbol}</div>
        <div class="nm">${item.name} · ${item.sector}</div>
        <div class="match-pill">${item.match}% match</div>
      </div>
      <div class="klass">${item.asset_class}</div>
    </div>
    <div class="why">“${item.why}”</div>
    <div class="spark">${sparkSVG(item.sparkline, item.period_return)}</div>
    <div class="ret">1y change: <span class="${retCls}">${ret>=0?"+":""}${ret}%</span> ${item.data_source==="fallback"?"· demo data":""}</div>
    <div class="sliders">
      ${sliderRow("Volatility", item.scores.volatility, "fill-vol")}
      ${sliderRow("Stability", item.scores.stability, "fill-stab")}
      ${sliderRow("Reputation", item.scores.reputation, "fill-rep")}
    </div>
    <div class="desc">${item.description}</div>`;
  return card;
}

function sliderRow(label, val, cls) {
  return `<div class="slider-row">
    <div class="lbl"><span>${label}</span><span>${val}/100</span></div>
    <div class="slider-track"><div class="slider-fill ${cls}" style="width:${val}%"></div></div>
  </div>`;
}

function sparkSVG(points, ret) {
  if (!points || points.length < 2) return "";
  const w = 360, h = 70, pad = 4;
  const min = Math.min(...points), max = Math.max(...points);
  const span = (max - min) || 1;
  const stepX = (w - pad*2) / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = pad + i*stepX;
    const y = pad + (h - pad*2) * (1 - (p - min)/span);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = ret >= 0 ? "#2ecc71" : "#ff5a7e";
  const area = `M${coords[0]} L${coords.join(" L")} L${pad+(points.length-1)*stepX},${h} L${pad},${h} Z`;
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
    <path d="${area}" fill="${color}" opacity="0.12"/>
    <polyline points="${coords.join(" ")}" fill="none" stroke="${color}" stroke-width="2"/>
  </svg>`;
}

function topCard() { const d = $("deck"); return d.lastElementChild?.classList.contains("card") ? d.lastElementChild : null; }

/* drag / swipe gesture */
function attachDrag(card) {
  let startX=0, startY=0, dx=0, dy=0, dragging=false;
  const onStart=(x,y)=>{ dragging=true; startX=x; startY=y; card.style.transition="none"; };
  const onMove=(x,y)=>{ if(!dragging) return; dx=x-startX; dy=y-startY;
    card.style.transform=`translate(${dx}px,${dy}px) rotate(${dx*0.06}deg)`;
    card.querySelector(".stamp.like").style.opacity = Math.max(0, Math.min(1, dx/100));
    card.querySelector(".stamp.nope").style.opacity = Math.max(0, Math.min(1, -dx/100));
  };
  const onEnd=()=>{ if(!dragging) return; dragging=false; card.style.transition="transform 0.3s ease";
    if (Math.abs(dx)>110){ flyOut(card, dx>0); swipeTop(dx>0, true); }
    else { card.style.transform=""; card.querySelectorAll(".stamp").forEach(s=>s.style.opacity=0); }
    dx=0; dy=0;
  };
  card.addEventListener("mousedown",(e)=>onStart(e.clientX,e.clientY));
  window.addEventListener("mousemove",(e)=>onMove(e.clientX,e.clientY));
  window.addEventListener("mouseup",onEnd);
  card.addEventListener("touchstart",(e)=>onStart(e.touches[0].clientX,e.touches[0].clientY),{passive:true});
  card.addEventListener("touchmove",(e)=>onMove(e.touches[0].clientX,e.touches[0].clientY),{passive:true});
  card.addEventListener("touchend",onEnd);
}

function flyOut(card, liked) {
  card.style.transform = `translate(${liked?600:-600}px, -40px) rotate(${liked?40:-40}deg)`;
  card.style.opacity = "0";
}

async function swipeTop(liked, alreadyAnimated) {
  if (swipesExhausted()) { renderDeck(); return; }
  const item = S.deck[0];
  if (!item) return;
  const card = topCard();
  if (card && !alreadyAnimated) flyOut(card, liked);
  // record + get updated profile (the personalization loop)
  try {
    const res = await api("/api/swipe", {
      method: "POST",
      body: JSON.stringify({ session_id: S.sessionId, symbol: item.symbol, liked }),
    });
    S.personas = res.personas; S.vector = res.effective_vector;
    if (res.swipes_remaining != null) S.swipesRemaining = res.swipes_remaining;
    if (liked) {
      S.likes.push({ symbol:item.symbol, name:item.name, match:item.match, why:item.why });
      updateLikeCount();
    }
    updateMatchStrip();
    updateSwipeMeter();
  } catch (e) {
    // Most likely the daily swipe limit (HTTP 429) — stop here and reflect it.
    S.swipesRemaining = 0;
    updateSwipeMeter();
    renderDeck();
    return;
  }
  S.deck.shift();
  setTimeout(renderDeck, alreadyAnimated ? 300 : 260);
}

function updateLikeCount() {
  $("like-count").textContent = S.likes.length;
}

/* ---------------- modal detail ---------------- */
async function openModal(symbol) {
  const inst = await api(`/api/instrument/${symbol}`);
  const item = S.seen[symbol];                 // carries the user-specific "why"
  const md = inst.metadata || {};
  const strat = inst.strategy || {};

  const whyHtml = item && item.why ? `
    <div class="modal-section why-section">
      <div class="sec-title">Why you're seeing this</div>
      <div class="why-box">“${item.why}”</div>
    </div>` : "";

  const metaRows = [
    ["Asset type", md.asset_class_label],
    ["Risk level", md.risk_band],
    ["1y trend", md.trend],
    ["Liquidity", md.liquidity],
    ["Latest price", md.latest_price != null ? `$${md.latest_price}` : null],
    ["1y range", (md.period_low != null && md.period_high != null) ? `$${md.period_low} – $${md.period_high}` : null],
    ["Annualized volatility", inst.annualized_volatility != null ? `${(inst.annualized_volatility*100).toFixed(0)}%` : null],
  ].filter((r) => r[1] != null && r[1] !== "");
  const metaHtml = `<div class="meta-grid">${metaRows.map((r)=>`<div class="meta-k">${r[0]}</div><div class="meta-v">${r[1]}</div>`).join("")}</div>`;

  const stratHtml = strat.text ? `
    <div class="modal-section">
      <div class="sec-title">Suggested strategy</div>
      <p class="strat-thesis">${strat.thesis || ""}</p>
      <ul class="strat-list">
        ${strat.horizon ? `<li><b>Horizon:</b> ${strat.horizon}</li>` : ""}
        ${strat.sizing ? `<li><b>Position:</b> ${strat.sizing}</li>` : ""}
        ${strat.risk_management ? `<li><b>Risk management:</b> ${strat.risk_management}</li>` : ""}
      </ul>
    </div>` : "";

  $("modal-body").innerHTML = `
    <div class="card-top" style="border-radius:0">
      <div><h2 class="inst-name">${inst.name}</h2><div class="nm">${inst.symbol} · ${inst.sector}</div></div>
      <div class="klass">${inst.asset_class}</div>
    </div>
    <div class="chart-wrap">
      <div class="range-tabs" id="range-tabs"></div>
      <div class="chart-area" id="chart-area"></div>
      <div class="chart-tip hidden" id="chart-tip"></div>
    </div>
    <div class="ret" id="modal-change" style="padding:0 24px 12px"></div>
    <div class="sliders">
      ${sliderRow("Volatility", inst.scores.volatility, "fill-vol")}
      ${sliderRow("Stability", inst.scores.stability, "fill-stab")}
      ${sliderRow("Reputation", inst.scores.reputation, "fill-rep")}
    </div>
    <div class="modal-section"><div class="sec-title">Key facts</div>${metaHtml}</div>
    ${stratHtml}
    <div class="desc">${inst.description}</div>
    ${whyHtml}
    <p class="disclaimer compliance">Educational content only — not investment advice. Finter does not execute trades or hold funds.</p>`;
  $("modal").classList.remove("hidden");
  setupChart(inst.sparkline, inst.period_return);
}

/* Interactive price chart: hover/drag to read prices, switch time ranges (#6). */
const RANGE_FRAC = { "1M": 1 / 12, "3M": 0.25, "6M": 0.5, "1Y": 1 };
const RANGE_LABEL = { "1M": "1-month", "3M": "3-month", "6M": "6-month", "1Y": "1-year" };

function setupChart(points, periodReturn) {
  const tabs = $("range-tabs");
  tabs.innerHTML = "";
  let active = "1Y";
  Object.keys(RANGE_FRAC).forEach((id) => {
    const b = document.createElement("button");
    b.textContent = id;
    b.classList.toggle("active", id === active);
    b.onclick = () => {
      active = id;
      [...tabs.children].forEach((c) => c.classList.remove("active"));
      b.classList.add("active");
      drawChart(points, id);
    };
    tabs.appendChild(b);
  });
  drawChart(points, active);
}

function drawChart(allPoints, rangeId) {
  const area = $("chart-area");
  if (!allPoints || allPoints.length < 2) {
    area.innerHTML = `<div class="chart-empty">No price data available.</div>`;
    const changeEl = document.getElementById("modal-change");
    if (changeEl) changeEl.textContent = "";
    return;
  }
  const frac = RANGE_FRAC[rangeId] || 1;
  const n = Math.max(2, Math.round(allPoints.length * frac));
  const points = allPoints.slice(-n);
  const winRet = (points[points.length - 1] - points[0]) / (points[0] || 1);
  const w = 360, h = 120, pad = 6;
  const min = Math.min(...points), max = Math.max(...points);
  const span = (max - min) || 1;
  const stepX = (w - pad * 2) / (points.length - 1);
  const xy = points.map((p, i) => [pad + i * stepX, pad + (h - pad * 2) * (1 - (p - min) / span)]);
  const coords = xy.map((c) => `${c[0].toFixed(1)},${c[1].toFixed(1)}`);
  const color = winRet >= 0 ? "#2ecc71" : "#ff5a7e";
  // Surface the change for the *selected* range below the graph (req #6).
  const changeEl = document.getElementById("modal-change");
  if (changeEl) {
    const pct = (winRet * 100).toFixed(1);
    changeEl.innerHTML = `${RANGE_LABEL[rangeId] || "1-year"} change: <b class="${winRet >= 0 ? "pos" : "neg"}">${winRet >= 0 ? "+" : ""}${pct}%</b>`;
  }
  const areaPath = `M${coords[0]} L${coords.join(" L")} L${xy[xy.length - 1][0].toFixed(1)},${h} L${pad},${h} Z`;
  area.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
      <path d="${areaPath}" fill="${color}" opacity="0.12"/>
      <polyline points="${coords.join(" ")}" fill="none" stroke="${color}" stroke-width="2"/>
      <line class="chart-marker" x1="0" y1="0" x2="0" y2="${h}" stroke="#ffffff66" stroke-width="1" opacity="0"/>
      <circle class="chart-dot" r="3.5" fill="#fff" stroke="${color}" stroke-width="2" opacity="0"/>
    </svg>`;
  const svg = area.querySelector(".chart-svg");
  const marker = svg.querySelector(".chart-marker");
  const dot = svg.querySelector(".chart-dot");
  const tip = $("chart-tip");

  const move = (clientX) => {
    const rect = svg.getBoundingClientRect();
    const rel = Math.min(Math.max(clientX - rect.left, 0), rect.width);
    const vx = (rel / rect.width) * w;
    let idx = Math.round((vx - pad) / stepX);
    idx = Math.min(Math.max(idx, 0), points.length - 1);
    const [px, py] = xy[idx];
    marker.setAttribute("x1", px); marker.setAttribute("x2", px); marker.setAttribute("opacity", "1");
    dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.setAttribute("opacity", "1");
    const wrapRect = area.parentElement.getBoundingClientRect();
    tip.classList.remove("hidden");
    tip.textContent = `$${points[idx].toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    tip.style.left = (clientX - wrapRect.left) + "px";
    tip.style.top = (rect.top - wrapRect.top) + "px";
  };
  const hide = () => {
    marker.setAttribute("opacity", "0"); dot.setAttribute("opacity", "0"); tip.classList.add("hidden");
  };
  svg.onmousemove = (e) => move(e.clientX);
  svg.onmouseleave = hide;
  svg.addEventListener("touchstart", (e) => move(e.touches[0].clientX), { passive: true });
  svg.addEventListener("touchmove", (e) => move(e.touches[0].clientX), { passive: true });
  svg.addEventListener("touchend", hide);
}

/* ---------------- scenario quizzes (second-stage refinement) ---------------- */
async function startScenarios() {
  // Re-fetch every time so the Quizzes tab shows a fresh, random set of the
  // predefined scenarios on each visit.
  try {
    const { scenarios } = await api("/api/scenarios");
    S.scenarios = scenarios;
  } catch { if (!S.scenarios.length) return; }
  S.scenarioIdx = 0;
  S.scenarioAnswers = {};
  $("scenario-done").classList.add("hidden");
  $("scenario-body").classList.remove("hidden");
  show("screen-scenarios");
  renderScenario();
}

function renderScenario() {
  const s = S.scenarios[S.scenarioIdx];
  $("scenario-progress").style.width = `${(S.scenarioIdx / S.scenarios.length) * 100}%`;
  const body = $("scenario-body");
  body.innerHTML = `<div class="q-prompt">${s.prompt}</div>`;
  s.options.forEach((opt, i) => {
    const el = document.createElement("div");
    el.className = "q-opt";
    el.textContent = opt.label;
    el.onclick = () => { S.scenarioAnswers[s.id] = i; el.classList.add("sel"); setTimeout(nextScenario, 180); };
    body.appendChild(el);
  });
}

async function nextScenario() {
  S.scenarioIdx++;
  if (S.scenarioIdx < S.scenarios.length) { renderScenario(); return; }
  $("scenario-progress").style.width = "100%";
  const res = await api("/api/scenarios", {
    method: "POST",
    body: JSON.stringify({ session_id: S.sessionId, answers: S.scenarioAnswers }),
  });
  S.personas = res.personas; S.vector = res.effective_vector;
  // The profile sharpened — refresh the current deck to reflect it.
  if (S.activeClass) { try { await loadDeck(); } catch {} }
  $("scenario-body").classList.add("hidden");
  $("scenario-done").classList.remove("hidden");
}

/* ---------------- watchlist ---------------- */
async function loadWatchlist() {
  show("screen-likes");
  try {
    const res = await api(`/api/watchlist?session_id=${S.sessionId}`);
    S.watchlist = res.items || [];
  } catch { S.watchlist = []; }
  // Keep the badge + modal cache in sync with the server's view of the watchlist.
  S.likes = S.watchlist.map((i) => ({ symbol:i.symbol, name:i.name, match:i.match, why:i.why }));
  S.watchlist.forEach((i) => { S.seen[i.symbol] = i; });
  updateLikeCount();
  renderWatchlistFilters();
  renderLikes();
}

const KLASS_LABELS = { stock:"Stocks", etf:"ETFs", bond:"Bonds", crypto:"Crypto", cfd:"CFDs" };

function renderWatchlistFilters() {
  const bar = $("watchlist-filters");
  bar.innerHTML = "";
  const present = new Set(S.watchlist.map((i) => i.asset_class));
  if (!present.size) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const ids = ["all", "stock", "etf", "bond", "crypto", "cfd"]
    .filter((o) => o === "all" || present.has(o));
  if (!ids.includes(S.watchlistFilter)) S.watchlistFilter = "all";
  ids.forEach((id) => {
    const b = document.createElement("button");
    b.textContent = id === "all" ? "All" : (KLASS_LABELS[id] || id);
    b.classList.toggle("active", id === S.watchlistFilter);
    b.onclick = () => { S.watchlistFilter = id; renderWatchlistFilters(); renderLikes(); };
    bar.appendChild(b);
  });
}

function renderLikes() {
  const wrap = $("likes-list");
  let items = S.watchlist.slice();
  if (S.watchlistFilter !== "all") items = items.filter((i) => i.asset_class === S.watchlistFilter);
  items.sort((a, b) => b.match - a.match);   // highest matching first within the category
  if (!items.length) {
    wrap.innerHTML = S.watchlist.length
      ? `<p class="empty-note">Nothing in this category yet.</p>`
      : `<p class="empty-note">No likes yet — swipe right on what speaks to you.</p>`;
    return;
  }
  wrap.innerHTML = "";
  items.forEach((l) => {
    const el = document.createElement("div");
    el.className = "like-row";
    el.innerHTML = `
      <div class="l-main">
        <div class="l-sym">${l.symbol} <span class="l-klass">${l.asset_class}</span></div>
        <div class="l-nm">${l.name}</div>
      </div>
      <div class="l-right">
        <div class="l-match">${l.match}%</div>
        <button class="l-remove" title="Remove from watchlist">✕</button>
      </div>`;
    el.querySelector(".l-main").onclick = () => openModal(l.symbol);
    el.querySelector(".l-remove").onclick = (e) => { e.stopPropagation(); removeFromWatchlist(l.symbol); };
    wrap.appendChild(el);
  });
}

async function removeFromWatchlist(symbol) {
  try {
    const res = await api("/api/watchlist/remove", {
      method: "POST",
      body: JSON.stringify({ session_id: S.sessionId, symbol }),
    });
    // Removing it un-nudges the trait vector, so refresh persona/profile state.
    S.personas = res.personas; S.vector = res.effective_vector;
  } catch {}
  S.watchlist = S.watchlist.filter((i) => i.symbol !== symbol);
  S.likes = S.likes.filter((i) => i.symbol !== symbol);
  updateLikeCount();
  renderWatchlistFilters();
  renderLikes();
  // It can now resurface in Discover — refresh the deck so it reappears (#15).
  if (S.activeClass) { try { await loadDeck(); } catch {} }
}

/* kick off deck loading when entering it the first time */
const _origToDeck = $("to-deck-btn");
if (_origToDeck) _origToDeck.addEventListener("click", async () => {
  if (!S.assetClasses.length) await loadTabs();
  await loadDeck();
});

