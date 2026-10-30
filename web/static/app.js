const I18N = {
  de: {
    eyebrow: "Lokale Debattenmaschine",
    title: "Freiheit im Gespräch",
    subtitle: "Zwei trainierte Stimmen debattieren über Alltag, Gesellschaft und Freiheit.",
    statusReady: "Bereit",
    statusRunning: "Debatte läuft …",
    statusDone: "Abgeschlossen",
    statusStopped: "Gestoppt",
    statusError: "Fehler",
    config: "Debatte konfigurieren",
    topic: "Thema",
    topicPlaceholder: "Sind Frauen im jetzigen Alltag frei?",
    randomTopic: "Zufälliges Thema",
    mode: "Gesprächsmodus",
    modePolite: "Höflich",
    modeFree: "Frei",
    modeChaos: "Chaotisch",
    turns: "Runden",
    outcome: "Ergebnis",
    outcomeAuto: "Automatisch",
    outcomeAgree: "Einigung erzwingen",
    outcomeDisagree: "Uneinig bleiben",
    outcomeAngry: "Eskalation",
    outcomeRandom: "Zufällig",
    rotate: "Themenwechsel",
    agree: "Einigungsrunde nach jeder Runde",
    temperature: "Temperatur",
    autoLaunch: "llama-server automatisch starten",
    autoLaunchHint: "Ausgeschaltet werden bereits laufende Server auf Port 8081/8082 genutzt.",
    advanced: "Erweiterte Parameter",
    context: "Kontextgröße",
    tokens: "Max. Tokens",
    maxSentences: "Max. Sätze",
    cooldown: "Sperrzeit",
    dry: "DRY",
    mixEvery: "Wechsel alle",
    jointSentences: "Sätze der Einigung",
    accept: "Akzeptanzschwelle",
    attempts: "Versuche",
    patience: "Geduld",
    rage: "Eskalationsschwelle",
    dice: "Zufalls-Einwürfe",
    repeatGuard: "Wiederholungsschutz",
    debug: "Debug-Ausgabe",
    start: "Debatte starten",
    stop: "Stoppen",
    personas: "Die Stimmen",
    personaUS: "Solidarität (USA)",
    personaUSDesc: "Freiheit, Eigenverantwortung und offene Debatte.",
    personaDDR: "DDR",
    personaDDRDesc: "Gemeinschaft, Ordnung und soziale Sicherheit.",
    history: "Verlauf",
    refresh: "Aktualisieren",
    historyEmpty: "Noch keine Debatten gespeichert.",
    transcript: "Protokoll",
    transcriptEmptyTitle: "Noch kein Thema",
    export: "Exportieren",
    transcriptEmpty: "Wähle ein Thema und starte die Debatte.",
    serverLog: "Server-Log",
    moderator: "Moderator",
    joint: "Gemeinsame Erklärung",
    badgeInterrupt: "unterbrochen",
    badgeObjection: "Einwand",
    outcome_agree: "Einigung erreicht",
    outcome_disagree: "Uneinig, aber respektvoll",
    outcome_angry: "Abbruch: Streit eskaliert",
    unknownError: "Unbekannter Fehler",
    stopRequested: "Stopp angefordert …",
    connectionLost: "Verbindung unterbrochen.",
    topicRequired: "Bitte ein Thema eingeben.",
  },
  en: {
    eyebrow: "Local debate engine",
    title: "Freedom in Conversation",
    subtitle: "Two trained voices debate everyday life, society and freedom.",
    statusReady: "Ready",
    statusRunning: "Debate running …",
    statusDone: "Finished",
    statusStopped: "Stopped",
    statusError: "Error",
    config: "Configure debate",
    topic: "Topic",
    topicPlaceholder: "Are women free in everyday life today?",
    randomTopic: "Random topic",
    mode: "Debate mode",
    modePolite: "Polite",
    modeFree: "Free",
    modeChaos: "Chaotic",
    turns: "Turns",
    outcome: "Outcome",
    outcomeAuto: "Automatic",
    outcomeAgree: "Force agreement",
    outcomeDisagree: "Stay divided",
    outcomeAngry: "Escalation",
    outcomeRandom: "Random",
    rotate: "Scenario rotation",
    agree: "Joint statement after every round",
    temperature: "Temperature",
    autoLaunch: "Start llama-server automatically",
    autoLaunchHint: "When off, servers already running on ports 8081/8082 are used.",
    advanced: "Advanced parameters",
    context: "Context size",
    tokens: "Max tokens",
    maxSentences: "Max sentences",
    cooldown: "Cooldown",
    dry: "DRY",
    mixEvery: "Switch every",
    jointSentences: "Sentences per joint statement",
    accept: "Acceptance threshold",
    attempts: "Attempts",
    patience: "Patience",
    rage: "Escalation threshold",
    dice: "Random interjections",
    repeatGuard: "Repetition guard",
    debug: "Debug output",
    start: "Start debate",
    stop: "Stop",
    personas: "The voices",
    personaUS: "Solidarity (USA)",
    personaUSDesc: "Freedom, personal responsibility and open debate.",
    personaDDR: "GDR",
    personaDDRDesc: "Community, order and social security.",
    history: "History",
    refresh: "Refresh",
    historyEmpty: "No debates saved yet.",
    transcript: "Transcript",
    transcriptEmptyTitle: "No topic yet",
    export: "Export",
    transcriptEmpty: "Choose a topic and start the debate.",
    serverLog: "Server log",
    moderator: "Moderator",
    joint: "Joint statement",
    badgeInterrupt: "interrupted",
    badgeObjection: "Objection",
    outcome_agree: "Agreement reached",
    outcome_disagree: "Divided, but respectful",
    outcome_angry: "Aborted: conflict escalated",
    unknownError: "Unknown error",
    stopRequested: "Stop requested …",
    connectionLost: "Connection lost.",
    topicRequired: "Please enter a topic.",
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let lang = localStorage.getItem("religion-ai-lang") || "de";

const state = {
  lang,
  runId: null,
  running: false,
  es: null,
  current: null,
  nextObjection: false,
  lastSeq: -1,
  autoScroll: true,
  statusKey: "statusReady",
  history: [],
};

const transcriptEl = $("#transcript");
const logEl = $("#server-log");
const statusPill = $("#status-pill");
const statusText = $("#status-text");
const startBtn = $("#start-btn");
const stopBtn = $("#stop-btn");
const formError = $("#form-error");
const stageTopic = $("#stage-topic");

const t = (key) => (I18N[state.lang] && I18N[state.lang][key]) || I18N.de[key] || key;

function applyI18n() {
  document.documentElement.lang = state.lang === "de" ? "de" : "en";
  $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  $$(".lang-switch button").forEach((btn) => btn.classList.toggle("active", btn.dataset.lang === state.lang));
  statusText.textContent = t(state.statusKey);
  renderHistory();
}

function setStatus(key) {
  state.statusKey = key;
  const tone = {
    statusRunning: "running",
    statusDone: "done",
    statusStopped: "stopped",
    statusError: "error",
  }[key] || "";
  statusText.textContent = t(key);
  statusPill.className = "status-pill" + (tone ? " " + tone : "");
}

function showError(message) {
  formError.textContent = message || t("unknownError");
  formError.hidden = false;
}

function clearError() {
  formError.hidden = true;
  formError.textContent = "";
}

function log(text) {
  if (!text) return;
  const lines = logEl.textContent ? logEl.textContent.split("\n") : [];
  lines.push(text);
  while (lines.length > 300) lines.shift();
  logEl.textContent = lines.join("\n");
  logEl.scrollTop = logEl.scrollHeight;
}

function labelKey(speaker) {
  if (speaker === "solidarity_us") return "personaUS";
  if (speaker === "ddr") return "personaDDR";
  return "moderator";
}

function maybeScroll(force = false) {
  if (force || state.autoScroll) {
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }
}

function clearStreaming() {
  if (state.current && state.current.el) {
    state.current.el.classList.remove("streaming");
  }
}

function resetTranscript() {
  transcriptEl.innerHTML = "";
  state.current = null;
  state.nextObjection = false;
  state.autoScroll = true;
  stageTopic.textContent = t("transcriptEmptyTitle");
  stageTopic.removeAttribute("data-i18n");
}

function badge(key, variant) {
  const span = document.createElement("span");
  span.className = "badge" + (variant ? " " + variant : "");
  span.dataset.i18n = key;
  span.textContent = t(key);
  return span;
}

function addTopic(topic) {
  stageTopic.textContent = topic;
  stageTopic.removeAttribute("data-i18n");
  const el = document.createElement("article");
  el.className = "message moderator";
  const head = document.createElement("div");
  head.className = "msg-head";
  const speaker = document.createElement("span");
  speaker.className = "msg-speaker";
  speaker.dataset.i18n = "moderator";
  speaker.textContent = t("moderator");
  head.append(speaker);
  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = topic;
  el.append(head, body);
  transcriptEl.append(el);
  maybeScroll(true);
}

function addTurn(ev) {
  clearStreaming();
  const speaker = ev.speaker === "moderator" ? "moderator" : ev.speaker;
  const el = document.createElement("article");
  const isModerator = speaker === "moderator";
  el.className = "message " + (isModerator ? "moderator" : speaker === "solidarity_us" ? "us" : "ddr");
  const objection = !isModerator && state.nextObjection;
  if (objection) el.classList.add("objection");

  const head = document.createElement("div");
  head.className = "msg-head";
  const speakerEl = document.createElement("span");
  speakerEl.className = "msg-speaker";
  speakerEl.dataset.i18n = labelKey(speaker);
  speakerEl.textContent = t(labelKey(speaker));
  head.append(speakerEl);
  if (objection) head.append(badge("badgeObjection", "objection"));

  const body = document.createElement("div");
  body.className = "msg-body";
  el.append(head, body);
  transcriptEl.append(el);

  state.current = { el, body, kind: "turn", lastJointSpeaker: null, lastJointSpan: null };
  state.nextObjection = false;
  el.classList.add("streaming");
  maybeScroll(true);
}

function addJoint() {
  clearStreaming();
  const el = document.createElement("article");
  el.className = "message joint";
  const head = document.createElement("div");
  head.className = "msg-head";
  const speakerEl = document.createElement("span");
  speakerEl.className = "msg-speaker";
  speakerEl.dataset.i18n = "joint";
  speakerEl.textContent = t("joint");
  head.append(speakerEl);
  const body = document.createElement("div");
  body.className = "msg-body";
  el.append(head, body);
  transcriptEl.append(el);
  state.current = { el, body, kind: "joint", lastJointSpeaker: null, lastJointSpan: null };
  el.classList.add("streaming");
  maybeScroll(true);
}

function addDelta(ev) {
  if (!state.current) {
    addTurn({ speaker: ev.speaker === "moderator" ? "moderator" : ev.speaker || "solidarity_us", section: "turn" });
  }
  const current = state.current;
  if (current.kind === "joint" && (ev.speaker === "solidarity_us" || ev.speaker === "ddr")) {
    if (current.lastJointSpeaker !== ev.speaker || !current.lastJointSpan) {
      const span = document.createElement("span");
      span.className = "joint-part " + (ev.speaker === "solidarity_us" ? "us" : "ddr");
      current.body.append(span);
      current.lastJointSpan = span;
      current.lastJointSpeaker = ev.speaker;
    }
    current.lastJointSpan.textContent += ev.text;
  } else {
    current.lastJointSpeaker = null;
    current.lastJointSpan = null;
    current.body.append(document.createTextNode(ev.text));
  }
  maybeScroll();
}

function markInterrupt() {
  if (!state.current) return;
  state.current.el.classList.add("interrupted");
  const head = state.current.el.querySelector(".msg-head");
  if (head && !head.querySelector(".badge.interrupt")) {
    head.append(badge("badgeInterrupt", "interrupt"));
  }
  state.nextObjection = true;
}

function addLine(ev) {
  const speaker = ev.speaker || "solidarity_us";
  const el = document.createElement("article");
  el.className = "message line " + (speaker === "ddr" ? "ddr" : "us");
  const head = document.createElement("div");
  head.className = "msg-head";
  const speakerEl = document.createElement("span");
  speakerEl.className = "msg-speaker";
  speakerEl.dataset.i18n = labelKey(speaker);
  speakerEl.textContent = t(labelKey(speaker));
  head.append(speakerEl);
  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = ev.text || "";
  el.append(head, body);
  transcriptEl.append(el);
  state.current = null;
  maybeScroll();
}

function addOutcome(outcome) {
  clearStreaming();
  const el = document.createElement("div");
  el.className = "outcome " + outcome;
  el.dataset.i18n = "outcome_" + outcome;
  el.textContent = t("outcome_" + outcome);
  transcriptEl.append(el);
  state.current = null;
  maybeScroll();
}

function handleEvent(ev) {
  switch (ev.type) {
    case "status":
      if (ev.text) log(ev.text);
      if (ev.state === "running") setStatus("statusRunning");
      break;
    case "topic":
      addTopic(ev.topic);
      break;
    case "turn_start":
      addTurn(ev);
      break;
    case "joint_start":
      addJoint();
      break;
    case "delta":
      addDelta(ev);
      break;
    case "interrupt":
      markInterrupt();
      break;
    case "line":
      addLine(ev);
      break;
    case "outcome":
      addOutcome(ev.outcome);
      break;
    case "error":
      log("ERROR: " + (ev.text || t("unknownError")));
      showError(ev.text || t("unknownError"));
      setStatus("statusError");
      break;
    case "end":
      finish(ev.status);
      break;
    default:
      break;
  }
}

function finish(status) {
  state.running = false;
  if (state.es) {
    state.es.close();
    state.es = null;
  }
  clearStreaming();
  if (status === "done") setStatus("statusDone");
  else if (status === "stopped") setStatus("statusStopped");
  else if (status === "error") setStatus("statusError");
  else setStatus("statusReady");
  updateButtons();
  loadHistory();
  maybeScroll(true);
}

function connect(id) {
  if (state.es) state.es.close();
  const es = new EventSource(`/api/runs/${encodeURIComponent(id)}/stream`);
  state.es = es;
  es.onmessage = (message) => {
    let ev;
    try {
      ev = JSON.parse(message.data);
    } catch {
      return;
    }
    if (typeof ev.seq === "number") {
      if (ev.seq <= state.lastSeq) return;
      state.lastSeq = ev.seq;
    }
    handleEvent(ev);
  };
  es.onerror = () => {
    if (!state.running && state.es) {
      state.es.close();
      state.es = null;
    }
  };
}

function updateButtons() {
  startBtn.disabled = state.running;
  stopBtn.disabled = !state.running || !state.runId;
  $$("#export-actions button").forEach((btn) => { btn.disabled = !state.runId; });
}

function numberValue(id, fallback) {
  const value = Number.parseFloat($(id).value);
  return Number.isFinite(value) ? value : fallback;
}

function intValue(id, fallback) {
  const value = Number.parseInt($(id).value, 10);
  return Number.isFinite(value) ? value : fallback;
}

function collectParams() {
  const rawDice = $("#dice").value.trim();
  return {
    topic: $("#topic").value.trim(),
    mode: $("#mode").value,
    turns: intValue("#turns", 7),
    rotate: intValue("#rotate", 0),
    agree: $("#agree").checked,
    outcome: $("#outcome").value,
    temperature: numberValue("#temperature", 0.8),
    dice: rawDice === "" ? null : Number.parseFloat(rawDice),
    auto_launch: $("#auto-launch").checked,
    context: intValue("#context", 4096),
    tokens: intValue("#tokens", 160),
    max_sentences: intValue("#max-sentences", 2),
    cooldown: intValue("#cooldown", 3),
    dry: numberValue("#dry", 0.8),
    repeat_guard: $("#repeat-guard").checked,
    mix_every: intValue("#mix-every", 1),
    joint_sentences: intValue("#joint-sentences", 3),
    accept: numberValue("#accept", 0.35),
    attempts: intValue("#attempts", 2),
    patience: intValue("#patience", 4),
    rage: intValue("#rage", 3),
    debug: $("#debug").checked,
  };
}

function errorText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return detail ? JSON.stringify(detail) : t("unknownError");
}

async function startRun(event) {
  event.preventDefault();
  if (state.running) return;
  clearError();
  const params = collectParams();
  if (!params.topic) {
    showError(t("topicRequired"));
    $("#topic").focus();
    return;
  }
  startBtn.disabled = true;
  stopBtn.disabled = true;
  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(errorText(payload.detail) || response.statusText);
    }
    const data = await response.json();
    state.runId = data.id;
    state.running = true;
    state.lastSeq = -1;
    resetTranscript();
    logEl.textContent = "";
    setStatus("statusRunning");
    updateButtons();
    connect(data.id);
    loadHistory();
  } catch (error) {
    state.running = false;
    setStatus("statusError");
    showError(String(error.message || error));
    updateButtons();
  }
}

async function stopRun() {
  if (!state.runId) return;
  stopBtn.disabled = true;
  log(t("stopRequested"));
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(state.runId)}/stop`, { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(errorText(payload.detail) || response.statusText);
    }
  } catch (error) {
    showError(String(error.message || error));
    updateButtons();
  }
}

function replayRecord(record) {
  resetTranscript();
  logEl.textContent = "";
  state.lastSeq = -1;
  state.nextObjection = false;
  for (const ev of record.events || []) {
    if (typeof ev.seq === "number") state.lastSeq = Math.max(state.lastSeq, ev.seq);
    handleEvent(ev);
  }
  if (!record.events || !record.events.some((ev) => ev.type === "end")) {
    finish(record.status === "running" ? "running" : record.status);
  }
}

async function openRun(id) {
  if (state.running && id !== state.runId) return;
  clearError();
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(response.statusText);
    const record = await response.json();
    state.runId = id;
    state.running = record.status === "running" || record.status === "starting";
    replayRecord(record);
    if (state.running) {
      setStatus("statusRunning");
      connect(id);
    }
    updateButtons();
    renderHistory();
  } catch (error) {
    showError(String(error.message || error));
  }
}

function renderHistory() {
  const list = $("#history-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.history.length) {
    const item = document.createElement("li");
    item.className = "muted";
    item.textContent = t("historyEmpty");
    list.append(item);
    return;
  }
  for (const run of state.history) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item" + (run.id === state.runId ? " active" : "");
    const topic = document.createElement("span");
    topic.className = "history-topic";
    topic.textContent = run.topic || "—";
    const meta = document.createElement("span");
    meta.className = "history-meta";
    const when = run.created ? new Date(run.created * 1000).toLocaleString(state.lang === "de" ? "de-DE" : "en-US", { dateStyle: "short", timeStyle: "short" }) : "";
    const statusKey = {
      done: "statusDone",
      running: "statusRunning",
      starting: "statusRunning",
      stopped: "statusStopped",
      error: "statusError",
    }[run.status] || "statusReady";
    const outcome = run.outcome ? t("outcome_" + run.outcome) : t(statusKey);
    meta.textContent = [run.mode, outcome, when].filter(Boolean).join(" · ");
    button.append(topic, meta);
    button.addEventListener("click", () => openRun(run.id));
    item.append(button);
    list.append(item);
  }
}

async function loadHistory() {
  try {
    const response = await fetch("/api/runs");
    if (!response.ok) return;
    const data = await response.json();
    state.history = data.runs || [];
    renderHistory();
  } catch {
    /* history is optional */
  }
}

async function randomTopic() {
  try {
    const response = await fetch("/api/scenarios");
    if (!response.ok) return;
    const data = await response.json();
    const scenarios = data.scenarios || [];
    if (scenarios.length) {
      $("#topic").value = scenarios[Math.floor(Math.random() * scenarios.length)];
    }
  } catch {
    /* ignore */
  }
}

async function exportRuns(format) {
  if (!state.runId) return;
  window.location.href = `/api/runs/${encodeURIComponent(state.runId)}/export?format=${encodeURIComponent(format)}`;
}

function init() {
  applyI18n();
  updateButtons();
  setStatus("statusReady");
  loadHistory();

  $("#run-form").addEventListener("submit", startRun);
  stopBtn.addEventListener("click", stopRun);
  $("#random-topic").addEventListener("click", randomTopic);
  $("#refresh-history").addEventListener("click", loadHistory);
  $("#temperature").addEventListener("input", (event) => {
    $("#temperature-out").textContent = event.target.value;
  });
  $$("#export-actions button").forEach((btn) => {
    btn.addEventListener("click", () => exportRuns(btn.dataset.export));
  });
  $$(".lang-switch button").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.lang = btn.dataset.lang;
      localStorage.setItem("religion-ai-lang", state.lang);
      applyI18n();
    });
  });
  transcriptEl.addEventListener("scroll", () => {
    const distance = transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight;
    state.autoScroll = distance < 90;
  });
}

document.addEventListener("DOMContentLoaded", init);
