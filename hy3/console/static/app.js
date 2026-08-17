// HY3 Operator Console — frontend logic (vanilla ES modules, no build step).
// Talks to the read-only JSON API served by hy3/console/server.py. Layout is a
// Wireshark-style master/detail: session ribbon -> filterable event list ->
// selection-linked detail panes (event payload + job spec/payload/acceptance/diff).

const state = {
  sessions: [],
  currentSessionId: null,
  events: [],
  selectedId: null,
};

// --- tiny helpers -----------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, children = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) n.appendChild(c);
  return n;
};

async function api(path, { signal } = {}) {
  const res = await fetch(path, { signal });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function fmtTs(ms) {
  if (ms == null) return "—";
  const d = new Date(ms);
  if (isNaN(d)) return String(ms);
  return d.toISOString().replace("T", " ").replace("Z", "").slice(0, 23);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Minimal JSON syntax highlighter (safe: escapes first, then wraps tokens).
function highlightJson(obj) {
  let json = JSON.stringify(obj, null, 2);
  if (json === undefined) json = String(obj);
  json = escapeHtml(json);
  return json.replace(
    /("(?:\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false)\b|\bnull\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (m) => {
      let cls = "tok-num";
      if (/^"/.test(m)) cls = /:$/.test(m) ? "tok-key" : "tok-str";
      else if (/true|false/.test(m)) cls = "tok-bool";
      else if (/null/.test(m)) cls = "tok-null";
      return `<span class="${cls}">${m}</span>`;
    }
  );
}

function kindFamily(kind) {
  const root = String(kind || "").split(".")[0];
  const known = ["session", "plan", "job", "cap", "model", "accept", "gate", "egress", "snapshot", "rollback", "skill", "budget", "abort"];
  return known.includes(root) ? root : "other";
}

function riskClass(risk) {
  return "b-risk-" + (["read", "write", "destructive", "privileged"].includes(risk) ? risk : "read");
}

// --- sessions ----------------------------------------------------------------
async function loadSessions() {
  state.sessions = await api("/api/sessions?limit=100");
  renderRibbon();
  if (state.sessions.length && !state.currentSessionId) {
    selectSession(state.sessions[0].id);
  } else if (!state.sessions.length) {
    $("#session-ribbon").appendChild(el("div", { class: "session-chip", text: "No sessions yet — run `hy3 session new \"<goal>\"`." }));
  }
}

function renderRibbon() {
  const ribbon = $("#session-ribbon");
  ribbon.innerHTML = "";
  for (const s of state.sessions) {
    const chip = el("button", {
      class: "session-chip",
      type: "button",
      "aria-current": String(s.id === state.currentSessionId),
      onclick: () => selectSession(s.id),
    }, [
      el("div", { class: "sc-goal", text: s.goal || "(no goal)" }),
      el("div", { class: "sc-meta" }, [
        el("span", { class: `status-dot s-${s.status || "planning"}`, "aria-hidden": "true" }),
        el("span", { text: s.status || "?" }),
        el("span", { text: s.cost_usd != null ? `$${Number(s.cost_usd).toFixed(4)}` : "" }),
      ]),
    ]);
    ribbon.appendChild(chip);
  }
}

async function selectSession(id) {
  state.currentSessionId = id;
  state.selectedId = null;
  renderRibbon();
  $("#detail").innerHTML = '<div class="detail-empty">Loading events…</div>';
  await applyFilter(true);
}

// --- events ------------------------------------------------------------------
async function applyFilter(resetSelection = false) {
  if (!state.currentSessionId) return;
  const filter = $("#filter").value;
  const qs = new URLSearchParams({ filter, limit: "500" });
  const data = await api(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/events?${qs}`);
  state.events = data.events || [];
  renderFilterStatus(data);
  renderEvents();
  if (resetSelection && state.events.length) selectEvent(state.events[0].id);
  else if (!state.events.length) {
    state.selectedId = null;
    $("#detail").innerHTML = '<div class="detail-empty">No events match this filter.</div>';
  }
}

function renderFilterStatus(data) {
  const st = $("#filter-status");
  const errs = data.filter_errors || [];
  if (errs.length) {
    st.className = "filter-status err";
    st.textContent = "⚠ " + errs.join("  ");
  } else {
    st.className = "filter-status ok";
    st.textContent = "filter ok";
  }
  $("#event-count").textContent = `${data.count || 0} event(s)`;
}

function renderEvents() {
  const list = $("#event-list");
  list.innerHTML = "";
  for (const ev of state.events) {
    const fam = kindFamily(ev.kind);
    const isFailed = ["cap.error", "accept.fail", "gate.denied"].includes(ev.kind);
    const isGated = ev.kind && ev.kind.startsWith("gate.");
    const row = el("div", {
      class: "event-row" + (isFailed ? " is-failed" : "") + (isGated ? " is-gated" : ""),
      id: "ev-" + ev.id,
      role: "option",
      "aria-selected": String(ev.id === state.selectedId),
      "data-kind-family": fam,
      onclick: () => selectEvent(ev.id),
    }, [
      el("span", { class: "c-time", text: fmtTs(ev.ts) }),
      el("span", {}, [el("span", { class: `badge kind fam-${fam}`, text: ev.kind })]),
      el("span", { class: "c-cap", text: ev.capability_id || "—" }),
      el("span", {}, [ev.risk ? el("span", { class: `badge risk ${riskClass(ev.risk)}`, text: ev.risk }) : document.createTextNode("")]),
      el("span", { class: "c-sum", text: summarize(ev) }),
    ]);
    list.appendChild(row);
  }
  if (!state.events.length) {
    list.appendChild(el("div", { class: "detail-empty", text: "No events." }));
  }
}

function summarize(ev) {
  const p = ev.payload || {};
  if (ev.kind === "cap.call") return "call → " + truncate(JSON.stringify(p.inputs ?? {}));
  if (ev.kind === "cap.result") return "result ← " + truncate(JSON.stringify(p.result ?? {}));
  if (ev.kind === "cap.error") return "ERROR: " + truncate(String(p.error ?? ""));
  if (ev.kind === "accept.pass") return "accept ✓ " + truncate(JSON.stringify(p));
  if (ev.kind === "accept.fail") return "accept ✗ " + truncate(JSON.stringify(p));
  if (ev.kind === "gate.prompt") return "gate? " + truncate(String(p.prompt ?? ""));
  if (ev.kind === "gate.approved") return "gate ✓ " + truncate(String(p.reason ?? ""));
  if (ev.kind === "gate.denied") return "gate ✗ " + truncate(String(p.reason ?? ""));
  if (ev.kind === "session.start") return truncate(String(p.goal ?? ""));
  if (ev.kind === "snapshot.taken") return "snapshot " + truncate(String(p.path ?? ""));
  return truncate(JSON.stringify(p));
}

function truncate(s, n = 80) {
  s = String(s);
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// --- selection + detail ------------------------------------------------------
function moveSelection(delta) {
  if (!state.events.length) return;
  let idx = state.events.findIndex((e) => e.id === state.selectedId);
  if (idx < 0) idx = 0;
  else idx = Math.min(state.events.length - 1, Math.max(0, idx + delta));
  selectEvent(state.events[idx].id);
  const node = document.getElementById("ev-" + state.events[idx].id);
  if (node) node.scrollIntoView({ block: "nearest" });
}

async function selectEvent(id) {
  state.selectedId = id;
  // update selection highlight without a full re-render
  for (const row of document.querySelectorAll(".event-row")) {
    row.setAttribute("aria-selected", String(row.id === "ev-" + id));
  }
  const list = $("#event-list");
  if (list) list.setAttribute("aria-activedescendant", "ev-" + id);
  let ev;
  try {
    ev = await api(`/api/events/${encodeURIComponent(id)}`);
  } catch (e) {
    $("#detail").innerHTML = `<div class="detail-empty">Failed to load event: ${escapeHtml(e.message)}</div>`;
    return;
  }
  renderDetail(ev);
}

function renderDetail(ev) {
  const fam = kindFamily(ev.kind);
  const head = el("div", { class: "evt-head" }, [
    el("span", { class: "evt-title", text: ev.kind }),
    el("span", { class: `badge kind fam-${fam}`, text: ev.kind }),
    ev.risk ? el("span", { class: `badge risk ${riskClass(ev.risk)}`, text: ev.risk }) : null,
    ev.redacted ? el("span", { class: "redacted-flag", text: "REDACTED" }) : null,
  ]);
  const meta = el("dl", { class: "kv" }, [
    el("dt", { text: "event" }), el("dd", { text: ev.id }),
    el("dt", { text: "time" }), el("dd", { text: fmtTs(ev.ts) }),
    el("dt", { text: "capability" }), el("dd", { text: ev.capability_id || "—" }),
    el("dt", { text: "provider" }), el("dd", { text: ev.provider || "—" }),
    el("dt", { text: "run" }), el("dd", { text: ev.run_id || "—" }),
    el("dt", { text: "job" }), el("dd", { text: ev.job_id || "—" }),
  ]);

  const detail = $("#detail");
  detail.innerHTML = "";
  detail.appendChild(el("h2", { text: "Event" }));
  detail.appendChild(head);
  detail.appendChild(el("section", {}, [el("div", { class: "sec-title", text: "Metadata" }), meta]));

  // Payload
  detail.appendChild(el("section", {}, [
    el("div", { class: "sec-title", text: "Payload" }),
    el("pre", { class: "json" }, [el("code", { html: highlightJson(ev.payload ?? {}) })]),
  ]));

  // Job context (spec / payload / acceptance / diff)
  if (ev.job) renderJobContext(detail, ev.job);
}

function renderJobContext(detail, job) {
  const j = job.job || {};
  const specRows = el("dl", { class: "kv" }, [
    el("dt", { text: "job id" }), el("dd", { text: j.id || "—" }),
    el("dt", { text: "capability" }), el("dd", { text: j.capability_id || (job.spec && job.spec.capability_id) || "—" }),
    el("dt", { text: "profile" }), el("dd", { text: j.profile || (job.spec && job.spec.profile) || "—" }),
    el("dt", { text: "risk" }), el("dd", { text: j.risk || (job.spec && job.spec.risk) || "—" }),
    el("dt", { text: "depends_on" }), el("dd", { text: Array.isArray(j.depends_on) ? j.depends_on.join(", ") : (job.spec && (job.spec.depends_on || []).join(", ") || "—") }),
    el("dt", { text: "status" }), el("dd", { text: j.status || "—" }),
    el("dt", { text: "attempts" }), el("dd", { text: String(j.attempt ?? "—") }),
  ]);

  const tabs = el("div", { class: "tabs" });
  const panes = {};

  const mkTab = (key, label, build) => {
    const btn = el("button", { class: "tab", type: "button", "aria-pressed": "false", text: label });
    const pane = el("div", { class: "tab-pane", hidden: "true" });
    panes[key] = { btn, pane, build };
    btn.addEventListener("click", () => showTab(key));
    tabs.appendChild(btn);
    detail.appendChild(pane);
    return { btn, pane };
  };
  const showTab = (key) => {
    for (const k of Object.keys(panes)) {
      const active = k === key;
      panes[k].btn.setAttribute("aria-pressed", String(active));
      panes[k].pane.hidden = active ? null : "true";
    }
  };

  detail.appendChild(el("h2", { text: "Job context" }));
  detail.appendChild(el("section", {}, [el("div", { class: "sec-title", text: "Spec" }), specRows]));
  detail.appendChild(tabs);

  const { btn: bSpec, pane: pSpec } = mkTab("spec", "Spec", null);
  const { btn: bIn, pane: pIn } = mkTab("inputs", "Inputs", null);
  const { btn: bOut, pane: pOut } = mkTab("result", "Result", null);
  const { btn: bAcc, pane: pAcc } = mkTab("acceptance", "Acceptance", null);
  const { btn: bDiff, pane: pDiff } = mkTab("diff", "Diff", null);

  pSpec.appendChild(el("pre", { class: "json" }, [el("code", { html: highlightJson(job.spec ?? j) })]));
  pIn.appendChild(el("pre", { class: "json" }, [el("code", { html: highlightJson(job.call_inputs ?? null) })]));
  pOut.appendChild(el("pre", { class: "json" }, [el("code", { html: highlightJson(job.result ?? null) })]));
  pAcc.appendChild(el("pre", { class: "json" }, [el("code", { html: highlightJson(job.acceptance ?? null) })]));
  pDiff.appendChild(renderDiff(job.call_inputs, job.result));

  showTab("diff");
}

function renderDiff(a, b) {
  const wrap = el("div");
  if (!a || typeof a !== "object" || Array.isArray(a) || !b || typeof b !== "object" || Array.isArray(b)) {
    wrap.appendChild(el("div", { class: "diff-note", text: "No structural diff: inputs/result are not both objects." }));
    return wrap;
  }
  const added = [], changed = [], removed = [];
  const ak = Object.keys(a), bk = Object.keys(b);
  for (const k of bk) {
    if (!(k in a)) added.push(k);
    else if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) changed.push(k);
  }
  for (const k of ak) if (!(k in b)) removed.push(k);

  const ul = el("ul", { class: "diff-list" });
  const push = (cls, sign, k, val) => {
    const li = el("li");
    li.appendChild(el("span", { class: `diff-${cls}`, text: `${sign} ${k}` }));
    if (val !== undefined) li.appendChild(document.createTextNode("  " + truncate(JSON.stringify(val), 90)));
    ul.appendChild(li);
  };
  added.forEach((k) => push("add", "+", k, b[k]));
  changed.forEach((k) => push("chg", "~", k, b[k]));
  removed.forEach((k) => push("del", "-", k, a[k]));
  if (!added.length && !changed.length && !removed.length) {
    wrap.appendChild(el("div", { class: "diff-note", text: "inputs and result share the same top-level keys/values." }));
    return wrap;
  }
  wrap.appendChild(ul);
  return wrap;
}

// --- keyboard nav ------------------------------------------------------------
function wireKeyboard() {
  const list = $("#event-list");
  list.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); moveSelection(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveSelection(-1); }
    else if (e.key === "Home") { e.preventDefault(); if (state.events.length) selectEvent(state.events[0].id); }
    else if (e.key === "End") { e.preventDefault(); if (state.events.length) selectEvent(state.events[state.events.length - 1].id); }
    else if (e.key === "Enter" && state.selectedId) { e.preventDefault(); selectEvent(state.selectedId); }
  });
}

// --- boot --------------------------------------------------------------------
async function boot() {
  wireKeyboard();
  const filter = $("#filter");
  let t;
  filter.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => applyFilter(false), 180);
  });
  filter.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); applyFilter(false); }
    if (e.key === "ArrowDown") { e.preventDefault(); moveSelection(1); }
  });
  try {
    await loadSessions();
  } catch (e) {
    $("#session-ribbon").innerHTML = `<div class="session-chip">Console API error: ${escapeHtml(e.message)}</div>`;
  }
  filter.focus();
}

boot();
