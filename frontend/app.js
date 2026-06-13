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
  try {
    const h = await api("/api/health");
    const badge = $("llm-badge");
    badge.textContent = h.llm_backend === "ollama" ? "🦙 Llama" : "⚙ Heuristic";
    badge.className = "badge " + h.llm_backend;
  } catch { /* leave badge as-is */ }

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
  $("scenario-finish").onclick = () => show("screen-deck");
  document.querySelectorAll("#bottomnav button").forEach((b) => {
    b.onclick = () => {
      const target = b.dataset.screen;
      if (target === "screen-likes") renderLikes();
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
async function startInterview() {
  show("screen-interview");
  $("chat").innerHTML = "";
  S.interviewTurn = 0;
  S.transcript = [];
  addBubble("ai", "Hey! I'm your Finter guide. A few quick questions so I really get you 👇");
  await askNext();
}

async function askNext() {
  const { question, done } = await api(
    `/api/interview/next?session_id=${S.sessionId}&turn=${S.interviewTurn}`
  );
  if (done || !question) return finishInterview();
  S._pendingQ = question;
  setTimeout(() => addBubble("ai", question), 400);
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
  typing.remove();
  setTimeout(() => revealProfile(), 300);
}

/* ---------------- profile ---------------- */
function revealProfile() {
  show("screen-profile");
  renderPersonas(S.personas);
  drawRadar(S.vector);
}

async function refreshProfile() {
  try {
    const p = await api(`/api/profile?session_id=${S.sessionId}`);
    S.personas = p.personas; S.vector = p.effective_vector;
    renderPersonas(p.personas);
    drawRadar(p.effective_vector);
  } catch {}
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
const TRAIT_SHORT = { risk_tolerance:"Risk+", risk_aversion:"Safe", patience:"Patient", impulsivity:"Impulse", discipline:"Disc.", greed:"Greed", confidence:"Conf.", analytical_depth:"Analysis", contrarian_tendency:"Contra", herd_mentality:"Herd" };

function drawRadar(vec) {
  const c = $("radar"); const ctx = c.getContext("2d");
  const W = c.width, H = c.height, cx = W/2, cy = H/2, R = 100;
  const n = TRAIT_ORDER.length;
  ctx.clearRect(0,0,W,H);
  // grid
  ctx.strokeStyle = "#ffffff22"; ctx.fillStyle = "#9aa0bd"; ctx.font = "9px sans-serif"; ctx.textAlign = "center";
  for (let ring=1; ring<=3; ring++) {
    ctx.beginPath();
    for (let i=0;i<=n;i++){ const a=(i/n)*Math.PI*2 - Math.PI/2; const r=R*ring/3; const x=cx+r*Math.cos(a), y=cy+r*Math.sin(a); i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.stroke();
  }
  // axes + labels
  for (let i=0;i<n;i++){ const a=(i/n)*Math.PI*2 - Math.PI/2;
    ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(cx+R*Math.cos(a), cy+R*Math.sin(a)); ctx.stroke();
    const lx=cx+(R+16)*Math.cos(a), ly=cy+(R+16)*Math.sin(a);
    ctx.fillText(TRAIT_SHORT[TRAIT_ORDER[i]], lx, ly+3);
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
  const res = await api(`/api/recommend?session_id=${S.sessionId}&asset_class=${S.activeClass}&limit=20`);
  S.deck = res.items.filter((i) => !i.already_swiped);
  res.items.forEach((i) => { S.seen[i.symbol] = i; });  // keep why + strategy for the modal
  renderDeck();
  updateMatchStrip();
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
  const item = S.deck[0];
  if (!item) return;
  const card = topCard();
  if (card && !alreadyAnimated) flyOut(card, liked);
  if (liked) S.likes.push({ symbol:item.symbol, name:item.name, match:item.match, why:item.why });
  $("like-count").textContent = S.likes.length;
  // record + get updated profile (the personalization loop)
  try {
    const res = await api("/api/swipe", {
      method: "POST",
      body: JSON.stringify({ session_id: S.sessionId, symbol: item.symbol, liked }),
    });
    S.personas = res.personas; S.vector = res.effective_vector;
    updateMatchStrip();
  } catch {}
  S.deck.shift();
  setTimeout(renderDeck, alreadyAnimated ? 300 : 260);
}

/* ---------------- modal detail ---------------- */
async function openModal(symbol) {
  const inst = await api(`/api/instrument/${symbol}`);
  const item = S.seen[symbol];                 // carries the user-specific "why"
  const ret = (inst.period_return*100).toFixed(1);
  const md = inst.metadata || {};
  const strat = inst.strategy || {};

  const whyHtml = item && item.why ? `
    <div class="modal-section">
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
      <p class="disclaimer">Educational only — not investment advice.</p>
    </div>` : "";

  $("modal-body").innerHTML = `
    <div class="card-top" style="border-radius:18px 18px 0 0">
      <div><div class="sym">${inst.symbol}</div><div class="nm">${inst.name} · ${inst.sector}</div></div>
      <div class="klass">${inst.asset_class}</div>
    </div>
    <div class="spark">${sparkSVG(inst.sparkline, inst.period_return)}</div>
    <div class="ret" style="padding:0 18px 12px">1-year change: <b>${ret>=0?"+":""}${ret}%</b></div>
    <div class="sliders">
      ${sliderRow("Volatility", inst.scores.volatility, "fill-vol")}
      ${sliderRow("Stability", inst.scores.stability, "fill-stab")}
      ${sliderRow("Reputation", inst.scores.reputation, "fill-rep")}
    </div>
    ${whyHtml}
    <div class="modal-section"><div class="sec-title">Key facts</div>${metaHtml}</div>
    ${stratHtml}
    <div class="desc">${inst.description}</div>`;
  $("modal").classList.remove("hidden");
}

/* ---------------- scenario quizzes (second-stage refinement) ---------------- */
async function startScenarios() {
  if (!S.scenarios.length) {
    const { scenarios } = await api("/api/scenarios");
    S.scenarios = scenarios;
  }
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

/* ---------------- likes ---------------- */
function renderLikes() {
  const wrap = $("likes-list");
  if (!S.likes.length) { wrap.innerHTML = `<p class="empty-note">No likes yet — swipe right on what speaks to you.</p>`; return; }
  wrap.innerHTML = "";
  S.likes.slice().reverse().forEach((l) => {
    const el = document.createElement("div");
    el.className = "like-row";
    el.innerHTML = `<div><div class="l-sym">${l.symbol}</div><div class="l-nm">${l.name}</div></div><div class="l-match">${l.match}%</div>`;
    el.onclick = () => openModal(l.symbol);
    wrap.appendChild(el);
  });
}

/* kick off deck loading when entering it the first time */
const _origToDeck = $("to-deck-btn");
if (_origToDeck) _origToDeck.addEventListener("click", async () => {
  if (!S.assetClasses.length) await loadTabs();
  await loadDeck();
});

