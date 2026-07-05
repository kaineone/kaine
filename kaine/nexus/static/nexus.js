/* ---- Shared diagnostics SSE dispatcher (ONE EventSource, pub/sub fan-out) -
   Every feature below used to construct its OWN EventSource against
   "/diagnostics/stream" — up to 8 concurrent connections from a single
   console tab. Browsers cap ~6 concurrent HTTP/1.1 connections per host, so
   8 SSE plus the polling fetches saturated the pool: streams stalled and
   polls queued behind them. NexusStream opens exactly ONE connection and
   fans each parsed message out to every subscriber — this is what collapses
   the console back under the connection cap and is the single biggest
   smoothness win.

   It also owns the tab-visibility lifecycle (pause while `document.hidden`,
   a backgrounded phone tab must not stream forever) and exposes a connection
   state ("connecting"|"live"|"reconnecting"|"paused") other UI (NexusConn) can
   render so a dropped Tailscale link is visible rather than silently freezing
   the dashboard on stale numbers. --------------------------------------- */
(function () {
  var DEFAULT_URL = "/diagnostics/stream";
  var url = DEFAULT_URL;
  var es = null;
  var subscribers = [];        // fn(parsedMessage)
  var statusSubscribers = [];  // fn(state)
  var state = "connecting";
  var pausedForHidden = false;

  function setState(next) {
    if (state === next) return;
    state = next;
    statusSubscribers.forEach(function (fn) {
      try { fn(state); } catch (e) { if (window.console) console.error("NexusStream status subscriber", e); }
    });
  }

  function open() {
    if (es || typeof EventSource === "undefined") return;
    setState(state === "paused" ? "reconnecting" : "connecting");
    es = new EventSource(url);
    es.onopen = function () { setState("live"); };
    es.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (!msg) return;
      subscribers.forEach(function (fn) {
        try { fn(msg); } catch (e) { if (window.console) console.error("NexusStream subscriber", e); }
      });
    };
    // The browser auto-retries a dropped SSE connection on its own; reflect
    // that visually instead of treating it as fatal.
    es.onerror = function () { setState("reconnecting"); };
  }

  function close() {
    if (es) { es.close(); es = null; }
  }

  function init(streamUrl) {
    url = streamUrl || DEFAULT_URL;
    open();
  }

  function subscribe(fn) {
    subscribers.push(fn);
    return function unsubscribe() {
      var i = subscribers.indexOf(fn);
      if (i !== -1) subscribers.splice(i, 1);
    };
  }

  function onStatus(fn) {
    statusSubscribers.push(fn);
    fn(state); // seed the caller with the current state immediately
    return function unsubscribe() {
      var i = statusSubscribers.indexOf(fn);
      if (i !== -1) statusSubscribers.splice(i, 1);
    };
  }

  // Pause the live connection while the tab is hidden and resume — with a
  // fresh connection — when it becomes visible again (task 1.4).
  if (typeof document !== "undefined" && "hidden" in document) {
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        if (es) { pausedForHidden = true; close(); setState("paused"); }
      } else if (pausedForHidden) {
        pausedForHidden = false;
        open();
      }
    });
  }

  window.NexusStream = {
    init: init,
    subscribe: subscribe,
    onStatus: onStatus,
    state: function () { return state; },
  };
})();

/* ---- Pauseable poll intervals ---------------------------------------------
   A thin `setInterval` wrapper that stops firing entirely while the tab is
   hidden (rather than polling uselessly in the background) and resumes — with
   an immediate refresh — when it becomes visible again. Used by the handful
   of features that still poll a JSON endpoint on a timer (task 1.4). */
(function () {
  function pausable(fn, ms) {
    var timer = null;
    function start() { if (timer === null) timer = setInterval(fn, ms); }
    function stop() { if (timer !== null) { clearInterval(timer); timer = null; } }
    if (typeof document !== "undefined" && "hidden" in document) {
      document.addEventListener("visibilitychange", function () {
        if (document.hidden) stop();
        else { start(); fn(); }
      });
    }
    var hiddenNow = typeof document !== "undefined" && document.hidden;
    if (!hiddenNow) start();
    return { start: start, stop: stop };
  }

  window.NexusVisibility = { pausable: pausable };
})();

/* ---- Connection-status indicator ------------------------------------------
   A small always-visible live/reconnecting/paused badge (see _base.html) so a
   dropped Tailscale link is OBVIOUS rather than the dashboard silently
   freezing on stale numbers (task 1.4). */
(function () {
  var LABELS = {
    connecting: "connecting…",
    live: "live",
    reconnecting: "reconnecting…",
    paused: "paused",
  };

  function attach() {
    var el = document.getElementById("nexus-conn");
    if (!el || !window.NexusStream) return;
    el.removeAttribute("hidden");
    var label = el.querySelector(".conn-status__label");
    NexusStream.onStatus(function (state) {
      el.dataset.state = state;
      if (label) label.textContent = LABELS[state] || state;
    });
  }

  window.NexusConn = { attach: attach };
})();

(function () {
  function subscribeMetrics() {
    if (!window.NexusStream) return;
    NexusStream.subscribe(function () {
      var el = document.getElementById("live-event-count");
      if (el) {
        var n = parseInt(el.dataset.count || "0") + 1;
        el.dataset.count = String(n);
        el.textContent = String(n);
      }
    });
  }

  window.NexusSSE = { subscribeMetrics: subscribeMetrics };
})();

/* ---- Global RED-ALERT frame --------------------------------------------- */
/* The whole console goes red when a freeze is initiated or a serious problem
   appears. A single set of flags is the source of truth; updateRedAlert()
   re-evaluates and toggles `.red-alert` on `.shell`. Other modules (freeze,
   spot, preservation, health) set their flag via NexusRedAlert.set(...) wherever
   their state changes, then this drives the frame. */
(function () {
  var flags = { frozen: false, spot: false, preservation: false, health: false };

  function updateRedAlert() {
    var on = flags.frozen || flags.spot || flags.preservation || flags.health;
    var shell = document.querySelector(".shell");
    if (shell) shell.classList.toggle("red-alert", on);
  }

  // Derive the "serious problem" health flag from a /diagnostics/health.json
  // snapshot: a down service, or the cycle honestly overrunning its target rate.
  // (Spot critical escalation is wired separately via applySpotState.)
  function evaluateHealth(data) {
    if (!data) return;
    var problem = false;
    var deps = data.dependencies || [];
    for (var i = 0; i < deps.length; i++) {
      if (deps[i] && deps[i].status === "down") { problem = true; break; }
    }
    if (data.cycle_pacing && data.cycle_pacing.overrunning) problem = true;
    flags.health = problem;
    updateRedAlert();
  }

  window.NexusRedAlert = {
    set: function (key, value) {
      if (Object.prototype.hasOwnProperty.call(flags, key)) {
        flags[key] = !!value;
        updateRedAlert();
      }
    },
    evaluateHealth: evaluateHealth,
    update: updateRedAlert,
  };
})();

(function () {
  // Update the toggle button + the active/desired cells optimistically from the
  // toggle response (the server echoes the new desired state).
  function applyToggleDesired(btn, surface, data, fallbackDesired) {
    let nowDesired = fallbackDesired;
    if (data) {
      nowDesired = surface === "audio"
        ? !!data.audio_live_desired
        : !!data.video_live_desired;
    }
    btn.dataset.active = nowDesired ? "false" : "true";
    btn.textContent = nowDesired ? "stop" : "start";
    const row = btn.closest("tr");
    if (row) {
      const cells = row.querySelectorAll("td");
      // cells: [surface, active, desired, last started, action]
      if (cells[2]) cells[2].textContent = nowDesired ? "on" : "off";
    }
  }

  // Poll /diagnostics/perception.json until `active` matches `desired`, or until
  // a bounded number of attempts elapse (so a stuck task never hangs the UI).
  async function pollUntilActive(surface, desired) {
    const key = surface === "audio" ? "audio_live_active" : "video_live_active";
    for (let i = 0; i < 8; i++) {
      await new Promise(function (res) { setTimeout(res, 400); });
      try {
        const r = await fetch("/diagnostics/perception.json");
        if (!r.ok) continue;
        const snap = await r.json();
        const active = !!snap[key];
        // Reflect the live active cell.
        const cell = document.querySelector(
          "tr td button.perception-toggle[data-surface='" + surface + "']"
        );
        const row = cell ? cell.closest("tr") : null;
        if (row) {
          const cells = row.querySelectorAll("td");
          if (cells[1]) cells[1].textContent = active ? "🔴 on" : "off";
        }
        if (active === desired) return;
      } catch (e) { /* transient — keep polling */ }
    }
  }

  function attach() {
    const buttons = document.querySelectorAll("button.perception-toggle");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const surface = btn.dataset.surface;
        const desired = btn.dataset.active === "true";
        if (desired && !confirm("Turn ON live " + surface + "? KAINE will see/hear continuously. Nothing is saved to disk.")) {
          return;
        }
        btn.disabled = true;
        try {
          const r = await fetch("/diagnostics/perception/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ surface: surface, active: desired }),
          });
          if (!r.ok) {
            alert("toggle failed: " + r.status);
            btn.disabled = false;
            return;
          }
          // Optimistic update from the response: flip the button to the
          // confirmed desired state immediately.
          let data = null;
          try { data = await r.json(); } catch (e) { /* ignore */ }
          applyToggleDesired(btn, surface, data, desired);
          // Then poll the runtime until `active` matches the desired state (the
          // live task starts/stops within ~1 poll interval) before re-enabling.
          await pollUntilActive(surface, desired);
        } catch (err) {
          alert("toggle error: " + err);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }
  // Reflect a confirmed locus change in place — no reload. Updates the
  // current-locus label, the three locus buttons' disabled state, and the
  // lock checkbox, from the server's echoed {locus, locus_locked} response
  // (the same optimistic-update pattern as applyToggleDesired/applyFrozen).
  function applyLocusUI(locus, locked) {
    const label = document.getElementById("locus-current");
    if (label) label.textContent = locus + (locked ? " 🔒 locked" : "");
    document.querySelectorAll("button.locus-set").forEach(function (b) {
      b.disabled = b.dataset.locus === locus;
    });
    const lockCb = document.getElementById("locus-lock");
    if (lockCb) {
      lockCb.checked = !!locked;
      lockCb.dataset.currentLocus = locus;
    }
  }

  function attachLocus() {
    const lockCb = document.getElementById("locus-lock");
    async function setLocus(locus, locked) {
      const r = await fetch("/diagnostics/perception/locus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ locus: locus, locked: locked }),
      });
      if (!r.ok) { alert("locus failed: " + r.status); return null; }
      try { return await r.json(); } catch (e) { return null; }
    }
    document.querySelectorAll("button.locus-set").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const locus = btn.dataset.locus;
        if (locus === "virtual" &&
            !confirm("Send KAINE into the VIRTUAL world? The real camera and mic will turn OFF.")) {
          return;
        }
        btn.disabled = true;
        try {
          const data = await setLocus(locus, lockCb ? lockCb.checked : null);
          if (data) applyLocusUI(data.locus, data.locus_locked);
        } catch (err) { alert("locus error: " + err); } finally { btn.disabled = false; }
      });
    });
    if (lockCb) {
      lockCb.addEventListener("change", async function () {
        try {
          const data = await setLocus(lockCb.dataset.currentLocus || "physical", lockCb.checked);
          if (data) applyLocusUI(data.locus, data.locus_locked);
        } catch (err) { alert("lock error: " + err); }
      });
    }
  }

  const _origAttach = attach;
  attach = function () { _origAttach(); attachLocus(); };
  window.NexusPerception = { attach: attach };
})();

/* ---- Live charts (uPlot) ------------------------------------------------- */
(function () {
  const RING = 240; // ~ a few minutes of points at a few Hz

  // Every uPlot instance we create, paired with its container element, so a
  // board that re-shows at a changed width (collapse → reopen) can re-fit.
  const PLOTS = [];

  function hasUPlot() {
    return typeof window.uPlot !== "undefined";
  }

  function showEmpty(el) {
    if (!el) return;
    if (el.querySelector(".chart-empty")) return;
    const msg = el.dataset.empty || "no data yet";
    const div = document.createElement("div");
    div.className = "chart-empty";
    div.textContent = msg;
    el.appendChild(div);
  }

  function clearEmpty(el) {
    const e = el && el.querySelector(".chart-empty");
    if (e) e.remove();
  }

  // A live time-series wrapper with a bounded ring buffer.
  function LiveSeries(el, seriesDefs, opts) {
    this.el = el;
    this.seriesDefs = seriesDefs;
    this.opts = opts || {};
    this.t = [];
    this.cols = seriesDefs.map(function () { return []; });
    this.plot = null;
  }
  LiveSeries.prototype._ensurePlot = function () {
    if (this.plot || !hasUPlot() || !this.el) return;
    clearEmpty(this.el);
    const width = this.el.clientWidth || 480;
    const series = [{}].concat(this.seriesDefs.map(function (d) {
      return { label: d.label, stroke: d.stroke, width: 1.5 };
    }));
    this.plot = new uPlot({
      width: width,
      height: this.opts.height || 170,
      series: series,
      scales: { x: { time: true } },
      axes: [
        { stroke: "#6D748C", grid: { stroke: "#2a3142" } },
        { stroke: "#6D748C", grid: { stroke: "#2a3142" } },
      ],
      legend: { show: true },
    }, this._data(), this.el);
    PLOTS.push({ el: this.el, plot: this.plot });
  };
  LiveSeries.prototype._data = function () {
    return [this.t].concat(this.cols);
  };
  LiveSeries.prototype.push = function (tsSeconds, values) {
    this.t.push(tsSeconds);
    for (let i = 0; i < this.cols.length; i++) {
      const v = values[i];
      this.cols[i].push(typeof v === "number" && isFinite(v) ? v : null);
    }
    while (this.t.length > RING) {
      this.t.shift();
      this.cols.forEach(function (c) { c.shift(); });
    }
    this._ensurePlot();
    if (this.plot) this.plot.setData(this._data());
  };

  // Horizontal bar chart from a {label: count} map (SVG-free, divs).
  function renderBars(containerId, mapObj) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = "";
    const entries = Object.entries(mapObj || {});
    if (!entries.length) {
      const d = document.createElement("div");
      d.className = "chart-empty";
      d.textContent = "no data yet";
      el.appendChild(d);
      return;
    }
    const max = Math.max.apply(null, entries.map(function (e) { return e[1] || 0; })) || 1;
    entries.sort(function (a, b) { return (b[1] || 0) - (a[1] || 0); });
    entries.forEach(function (e) {
      const row = document.createElement("div");
      row.className = "bar-row";
      const label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = e[0];
      const track = document.createElement("div");
      track.className = "bar-track";
      const fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.width = Math.round(((e[1] || 0) / max) * 100) + "%";
      track.appendChild(fill);
      const val = document.createElement("span");
      val.className = "bar-val";
      val.textContent = String(e[1]);
      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(val);
      el.appendChild(row);
    });
  }

  function nowSeconds() { return Date.now() / 1000; }

  // Diagnostics: live cycle-rate, affect (VAD), salience, coherence from the SSE stream.
  function attachDiagnostics() {
    const rateEl = document.getElementById("chart-rate");
    const affectEl = document.getElementById("chart-affect");
    const salienceEl = document.getElementById("chart-salience");
    const coherenceEl = document.getElementById("chart-coherence");
    showEmpty(rateEl); showEmpty(affectEl); showEmpty(salienceEl); showEmpty(coherenceEl);

    const rate = rateEl ? new LiveSeries(rateEl, [
      { label: "processing Hz", stroke: "#E7442A" },
      { label: "experiential Hz", stroke: "#9EA5BA" },
    ]) : null;
    const affect = affectEl ? new LiveSeries(affectEl, [
      { label: "valence", stroke: "#E7442A" },
      { label: "arousal", stroke: "#E0913A" },
      { label: "dominance", stroke: "#6D748C" },
    ]) : null;
    const salience = salienceEl ? new LiveSeries(salienceEl, [
      { label: "salience", stroke: "#E7442A" },
    ]) : null;
    // PLV coherence — fed from workspace.broadcast metadata['coherence'].
    // The coherence dict maps pair labels to PLV floats; we render the mean
    // across all pairs so the chart is a single line regardless of pair count.
    const coherence = coherenceEl ? new LiveSeries(coherenceEl, [
      { label: "mean PLV", stroke: "#9EA5BA" },
    ]) : null;

    if (!hasUPlot()) {
      console.warn("uPlot unavailable; charts disabled");
      return;
    }
    if (!window.NexusStream) return;

    NexusStream.subscribe(function (msg) {
      const t = nowSeconds();
      const p = msg.payload || {};

      if (rate && (msg.type === "cycle.rates" || "processing_rate_hz" in p || "experiential_rate_hz" in p)) {
        rate.push(t, [num(p.processing_rate_hz), num(p.experiential_rate_hz)]);
      }
      if (affect && (msg.source === "thymos" || "valence" in p || "arousal" in p || "dominance" in p)) {
        if ("valence" in p || "arousal" in p || "dominance" in p) {
          affect.push(t, [num(p.valence), num(p.arousal), num(p.dominance)]);
        }
      }
      if (salience && typeof msg.salience === "number") {
        salience.push(t, [msg.salience]);
      }
      // workspace.broadcast carries metadata.coherence (PLV dict or absent).
      if (coherence && msg.source === "cycle" && p.metadata) {
        const coh = p.metadata.coherence;
        if (coh && typeof coh === "object") {
          const vals = Object.values(coh).filter(function (v) { return typeof v === "number" && isFinite(v); });
          if (vals.length > 0) {
            const mean = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
            coherence.push(t, [mean]);
          }
        }
        // Absent coherence key (oscillator disabled) → no point pushed; chart stays flat.
      }
    });
  }

  // Fatigue trend chart — separate subscriber so it can be attached independently.
  // Reads soma.report fatigue_value; draws a reference line for the threshold.
  function attachFatigueChart() {
    const fatigueEl = document.getElementById("chart-fatigue");
    if (!fatigueEl || !hasUPlot()) { showEmpty(fatigueEl); return; }
    showEmpty(fatigueEl);
    if (!window.NexusStream) return;

    const fatigue = new LiveSeries(fatigueEl, [
      { label: "fatigue", stroke: "#E0913A" },
      { label: "threshold", stroke: "#f3603f" },
    ]);

    NexusStream.subscribe(function (msg) {
      const p = msg.payload || {};
      // soma.report carries fatigue_value and fatigue_threshold.
      if (msg.source === "soma" && msg.type === "soma.report" &&
          ("fatigue_value" in p || "fatigue_threshold" in p)) {
        fatigue.push(Date.now() / 1000, [num(p.fatigue_value), num(p.fatigue_threshold)]);
      }
    });
  }

  function num(v) {
    const n = typeof v === "number" ? v : parseFloat(v);
    return isFinite(n) ? n : null;
  }

  // Evaluation: batch summary.json → time-series + bar charts.
  async function attachEvaluation(summaryUrl) {
    ["chart-ab", "chart-voice", "chart-eidolon"].forEach(function (id) {
      showEmpty(document.getElementById(id));
    });
    let data;
    try {
      const r = await fetch(summaryUrl);
      if (!r.ok) return;
      data = await r.json();
    } catch (e) {
      console.warn("evaluation summary fetch failed", e);
      return;
    }

    if (hasUPlot()) {
      // A/B divergence series.
      const ab = (data.ab_divergence && data.ab_divergence.series) || [];
      seriesChart("chart-ab", ab, [
        { key: "divergence", label: "divergence", stroke: "#E7442A" },
      ]);
      // Voice alignment before/after.
      seriesChart("chart-voice", data.voice_tracking || [], [
        { key: "before", label: "before", stroke: "#6D748C" },
        { key: "after", label: "after", stroke: "#E0913A" },
      ]);
      // Eidolon accuracy.
      seriesChart("chart-eidolon", data.eidolon_accuracy || [], [
        { key: "aggregate", label: "accuracy", stroke: "#9EA5BA" },
      ]);
    }

    renderBars("chart-attribution-total", data.attribution_total || {});
    renderBars("chart-attribution-hour", data.attribution_hour || {});
    renderBars("chart-proactive", data.proactive_triggers || {});
  }

  function seriesChart(elId, rows, defs) {
    const el = document.getElementById(elId);
    if (!el || !rows || !rows.length) { showEmpty(el); return; }
    clearEmpty(el);
    const xs = rows.map(function (_, i) { return i; });
    const cols = defs.map(function (d) {
      return rows.map(function (r) { return num(r[d.key]); });
    });
    const plot = new uPlot({
      width: el.clientWidth || 480,
      height: 170,
      series: [{}].concat(defs.map(function (d) {
        return { label: d.label, stroke: d.stroke, width: 1.5 };
      })),
      scales: { x: { time: false } },
      axes: [
        { stroke: "#6D748C", grid: { stroke: "#2a3142" } },
        { stroke: "#6D748C", grid: { stroke: "#2a3142" } },
      ],
    }, [xs].concat(cols), el);
    PLOTS.push({ el: el, plot: plot });
  }

  // Re-fit any uPlot charts contained in `root` to their current width. Called
  // when a collapsible board is reopened so a chart shown at a new width re-fits.
  function resizeWithin(root) {
    if (!root) return;
    PLOTS.forEach(function (rec) {
      if (!rec.plot || !root.contains(rec.el)) return;
      const w = rec.el.clientWidth;
      if (w > 0) rec.plot.setSize({ width: w, height: rec.plot.height });
    });
  }

  window.NexusCharts = {
    attachDiagnostics: attachDiagnostics,
    attachFatigueChart: attachFatigueChart,
    attachEvaluation: attachEvaluation,
    renderBars: renderBars,
    resizeWithin: resizeWithin,
  };

  // Collapsible boards: when a <details class="board"> is opened, re-fit any
  // charts inside it (their container may have a different width than when the
  // chart was first drawn). `toggle` does not bubble, so listen in capture.
  document.addEventListener("toggle", function (ev) {
    const d = ev.target;
    if (!d || d.tagName !== "DETAILS" || !d.classList || !d.classList.contains("board")) return;
    if (d.open) resizeWithin(d);
  }, true);
})();

/* ---- Operator controls (rate / fork / merge) ----------------------------- */
(function () {
  function setStatus(id, text, ok) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.style.color = ok === false ? "#f87171" : ok === true ? "#4ade80" : "";
  }

  async function postJson(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { /* ignore */ }
    return { ok: r.ok, status: r.status, data: data };
  }

  // Append a fork/merge row to the forks table from the create response —
  // targeted DOM update instead of a full page reload (task 2.4), matching
  // the existing optimistic-update pattern (applyToggleDesired/applyFrozen).
  function appendForkRow(fork) {
    const tbody = document.querySelector("#forks table tbody");
    if (!tbody) return;
    const emptyRow = tbody.querySelector("td.muted");
    if (emptyRow) { const tr = emptyRow.closest("tr"); if (tr) tr.remove(); }
    function td(text, cls) {
      const d = document.createElement("td");
      if (cls) d.className = cls;
      d.textContent = text || "";
      return d;
    }
    const tr = document.createElement("tr");
    tr.appendChild(td(fork.id, "col-id"));
    tr.appendChild(td(fork.parent_id, "col-id"));
    tr.appendChild(td(fork.label));
    tr.appendChild(td(new Date().toISOString()));
    tr.appendChild(document.createElement("td")); // flags — none known client-side
    tbody.appendChild(tr);
  }

  function attach() {
    const rateForm = document.getElementById("rate-form");
    if (rateForm) {
      rateForm.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        const proc = parseFloat(document.getElementById("proc-rate").value);
        const exp = parseFloat(document.getElementById("exp-rate").value);
        const body = {};
        if (isFinite(proc)) body.processing_rate_hz = proc;
        if (isFinite(exp)) body.experiential_rate_hz = exp;
        if (!Object.keys(body).length) {
          setStatus("rate-status", "enter at least one rate", false);
          return;
        }
        if (!confirm("Change the entity's pacing to " +
            JSON.stringify(body) + "? This alters how fast KAINE thinks.")) {
          return;
        }
        const res = await postJson("/diagnostics/cycle/rates", body);
        setStatus("rate-status", res.ok ? "rates published" : "failed: " + res.status, res.ok);
      });
    }

    const forkForm = document.getElementById("fork-form");
    if (forkForm) {
      forkForm.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        const parent = document.getElementById("fork-parent").value.trim();
        const label = document.getElementById("fork-label").value.trim();
        if (!parent) { setStatus("fork-status", "parent id required", false); return; }
        if (!confirm("Create a fork from snapshot " + parent + "?")) return;
        const res = await postJson("/diagnostics/forks", { parent_id: parent, label: label, shed: [] });
        if (res.ok) {
          setStatus("fork-status", "forked → " + (res.data && res.data.id), true);
          if (res.data) appendForkRow(res.data);
          document.getElementById("fork-parent").value = "";
          document.getElementById("fork-label").value = "";
        } else {
          setStatus("fork-status", "failed: " + res.status, false);
        }
      });
    }

    const mergeForm = document.getElementById("merge-form");
    if (mergeForm) {
      mergeForm.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        const a = document.getElementById("merge-a").value.trim();
        const b = document.getElementById("merge-b").value.trim();
        const label = document.getElementById("merge-label").value.trim();
        if (!a || !b) { setStatus("merge-status", "both snapshot ids required", false); return; }
        if (!confirm("Merge snapshots " + a + " + " + b + "?")) return;
        const res = await postJson("/diagnostics/merges", { snapshot_a_id: a, snapshot_b_id: b, label: label });
        if (res.ok) {
          setStatus("merge-status", "merged → " + (res.data && res.data.id), true);
          // The merge response only carries one parent_id; show both source
          // snapshots (known client-side) so the row reads meaningfully.
          if (res.data) appendForkRow({ id: res.data.id, parent_id: a + " + " + b, label: res.data.label });
          document.getElementById("merge-a").value = "";
          document.getElementById("merge-b").value = "";
          document.getElementById("merge-label").value = "";
        } else {
          setStatus("merge-status", "failed: " + res.status, false);
        }
      });
    }
  }

  window.NexusControls = { attach: attach };
})();

/* ---- Spot supervisor alert (border + banner + console) ------------------- */
(function () {
  var MAX_LOG_LINES = 200;

  function applySpotState(state, module, message) {
    // A Spot CRITICAL escalation is a serious problem — light the global frame.
    if (window.NexusRedAlert) NexusRedAlert.set("spot", state === "critical");
    // Update the full-window alert overlay.
    var overlay = document.getElementById("spot-alert");
    if (overlay) {
      overlay.dataset.state = state || "ok";
    }

    // Update the banner visibility and content.
    var banner = document.getElementById("spot-banner");
    if (banner) {
      banner.dataset.state = state || "ok";
      // Re-apply class to pick up the right colour.
      banner.className = "spot-banner spot-banner--" + (state || "ok");
      if (state === "recovery" || state === "critical") {
        banner.removeAttribute("hidden");
      } else {
        banner.setAttribute("hidden", "");
      }
      // Populate label text.
      var label = banner.querySelector(".spot-banner__label");
      if (label) {
        label.textContent =
          state === "critical" ? "SPOT CRITICAL" :
          state === "recovery" ? "SPOT RECOVERY" :
          "SPOT";
      }
      var msgEl = document.getElementById("spot-banner-msg");
      if (msgEl) { msgEl.textContent = message || ""; }
      var detailEl = document.getElementById("spot-banner-detail");
      if (detailEl) { detailEl.textContent = module ? "module: " + module : ""; }
    }
  }

  function ensureSpotPlaceholder() {
    var log = document.getElementById("spot-console-log");
    if (!log) return;
    if (log.querySelector(".spot-log-line")) return; // real lines present
    if (log.querySelector(".spot-log-placeholder")) return; // already there
    var ph = document.createElement("span");
    ph.className = "spot-log-line spot-log-placeholder log-info";
    ph.textContent = "no incident events";
    log.appendChild(ph);
  }

  function appendLogLine(text, level) {
    var log = document.getElementById("spot-console-log");
    if (!log) return;
    // Drop the placeholder once a real line arrives.
    var ph = log.querySelector(".spot-log-placeholder");
    if (ph) ph.remove();
    var line = document.createElement("span");
    var lvl = (level || "info").toLowerCase();
    line.className = "spot-log-line log-" + lvl;
    line.textContent = text;
    log.appendChild(line);
    // Cap retained lines.
    var lines = log.querySelectorAll(".spot-log-line");
    if (lines.length > MAX_LOG_LINES) {
      for (var i = 0; i < lines.length - MAX_LOG_LINES; i++) {
        lines[i].remove();
      }
    }
    // Auto-scroll to bottom.
    log.scrollTop = log.scrollHeight;
  }

  function loadInitialState() {
    fetch("/diagnostics/health.json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        // Re-evaluate the global red-alert from the full health snapshot (down
        // service / overrunning cycle) on every (re)load of this fetch.
        if (window.NexusRedAlert) NexusRedAlert.evaluateHealth(data);
        if (!data.spot) return;
        var s = data.spot;
        applySpotState(s.state, s.module, s.message);
      })
      .catch(function (err) {
        console.warn("spot: health.json fetch failed", err);
      });
  }

  function attachSpotSSE() {
    if (!window.NexusStream) return;
    NexusStream.subscribe(function (msg) {
      // nexus.snapshot (task 2.2's periodic server push) carries the full
      // health snapshot, including the spot block — reconcile from it so a
      // reconnect (or simply a missed spot.status) never leaves the border
      // stale. Bridge-forwarded bus events additionally arrive as
      // msg.source === "spot" for instant reaction to a state change.
      if (msg.source === "nexus" && msg.type === "nexus.snapshot") {
        var health = msg.payload && msg.payload.health;
        if (health) {
          if (window.NexusRedAlert) NexusRedAlert.evaluateHealth(health);
          if (health.spot) applySpotState(health.spot.state, health.spot.module, health.spot.message);
        }
        return;
      }
      // Bridge emits {source, type, payload, ...} — spot publishes to spot.out
      // so msg.source === "spot".
      if (msg.source !== "spot") return;
      var p = msg.payload || {};
      if (msg.type === "spot.status") {
        applySpotState(p.state, p.module, p.message);
      } else if (msg.type === "spot.log") {
        var text = p.message || p.text || JSON.stringify(p);
        appendLogLine(text, p.level || "info");
      }
    });
  }

  window.NexusSpot = {
    init: function () {
      ensureSpotPlaceholder();
      loadInitialState();
      attachSpotSSE();
    },
  };
})();

/* ---- Freeze toggle (in-place DOM update — no full reload) ---------------- */
(function () {
  function applyFrozen(frozen, reason) {
    // A frozen cycle is an attention state — drive the global red-alert frame.
    if (window.NexusRedAlert) NexusRedAlert.set("frozen", frozen);
    var btn = document.getElementById("freeze-toggle");
    var status = document.getElementById("freeze-status");
    var section = document.getElementById("freeze-control");
    var banner = document.querySelector(".freeze-banner");
    if (status) status.textContent = frozen ? "frozen" : "running";
    if (btn) {
      btn.dataset.frozen = frozen ? "true" : "false";
      btn.textContent = frozen ? "resume cycle" : "freeze cycle";
    }
    if (section) {
      if (frozen) section.classList.add("frozen");
      else section.classList.remove("frozen");
    }
    // The freeze banner is rendered server-side; toggle its visibility in place
    // rather than reloading. If it does not exist yet we leave it (a reload-free
    // banner insert is out of scope; the status + section state already reflect).
    if (banner) {
      if (frozen) banner.removeAttribute("hidden");
      else banner.setAttribute("hidden", "");
    }
  }

  function attach() {
    var btn = document.getElementById("freeze-toggle");
    if (!btn) return;
    // Seed the global frame from the server-rendered initial freeze state.
    if (window.NexusRedAlert) NexusRedAlert.set("frozen", btn.dataset.frozen === "true");
    btn.addEventListener("click", async function () {
      var frozen = btn.dataset.frozen === "true";
      var reasonEl = document.getElementById("freeze-reason");
      var reason = frozen ? null : ((reasonEl && reasonEl.value) || null);
      var msg = document.getElementById("freeze-msg");
      // Initiating a freeze (currently running): light the frame optimistically
      // so the operator gets instant feedback before the POST round-trips.
      if (!frozen && window.NexusRedAlert) NexusRedAlert.set("frozen", true);
      btn.disabled = true; if (msg) msg.textContent = "…";
      try {
        var r = await fetch("/diagnostics/cycle/freeze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ frozen: !frozen, reason: reason }),
        });
        if (r.ok) {
          var data = null;
          try { data = await r.json(); } catch (e) { /* ignore */ }
          var nowFrozen = data ? !!data.frozen : !frozen;
          applyFrozen(nowFrozen, data ? data.reason : reason);
          if (msg) msg.textContent = nowFrozen ? "frozen" : "running";
        } else {
          // POST failed — revert the optimistic frame to the real prior state.
          if (window.NexusRedAlert) NexusRedAlert.set("frozen", frozen);
          if (msg) msg.textContent = "failed";
        }
      } catch (e) {
        if (window.NexusRedAlert) NexusRedAlert.set("frozen", frozen);
        if (msg) msg.textContent = "error";
      } finally {
        btn.disabled = false;
      }
    });
  }

  window.NexusFreeze = { attach: attach };
})();

/* ---- Preservation / welfare-protective events panel ---------------------- */
(function () {
  var MAX = 50;
  var STORE_KEY = "nexus.preservation.events";

  // EXACT allowlist mirrored from HealthProber._PRESERVATION_ALLOWED_FIELDS.
  // Anything outside this set is never read or rendered — no content can leak.
  function renderLine(logEl, ev) {
    var line = document.createElement("span");
    var transition = ev.transition || "";
    var failed = transition.indexOf("fail") !== -1;
    line.className = "preservation-line" + (failed ? " log-error" : "");
    // A failed preservation is a serious problem — latch the global red-alert.
    if (failed && window.NexusRedAlert) NexusRedAlert.set("preservation", true);
    if (ev.incident_id) line.dataset.incident = ev.incident_id;
    var parts = [];
    parts.push(ev.monitor || "preservation");
    if (transition) parts.push("· " + transition);
    if (ev.reason) parts.push("· reason: " + ev.reason);
    var action = ev.action_taken || ev.action;
    if (action) parts.push("· action: " + action);
    if (ev.preservation_id) parts.push("· preservation: " + ev.preservation_id);
    if (ev.snapshot_id) parts.push("· snapshot: " + ev.snapshot_id);
    line.textContent = parts.join(" ");
    logEl.appendChild(line);
    var lines = logEl.querySelectorAll(".preservation-line");
    if (lines.length > MAX) {
      for (var i = 0; i < lines.length - MAX; i++) lines[i].remove();
    }
    logEl.scrollTop = logEl.scrollHeight;
  }

  function loadStored() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }

  function store(events) {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(events.slice(-MAX))); }
    catch (e) { /* sessionStorage unavailable — non-fatal */ }
  }

  function fromPayload(msg) {
    var p = msg.payload || {};
    // Only the allowlisted, non-content fields.
    return {
      monitor: p.monitor,
      transition: p.transition,
      incident_id: p.incident_id,
      reason: p.reason,
      action: p.action,
      action_taken: p.action_taken,
      preservation_id: p.preservation_id,
      snapshot_id: p.snapshot_id,
      _type: msg.type,
    };
  }

  function init() {
    var logEl = document.getElementById("preservation-log");
    if (!logEl) return;
    var events = loadStored();
    // If the server backfilled lines, sessionStorage replay would duplicate; only
    // replay stored events when the server rendered none.
    if (!logEl.dataset.backfill && events.length) {
      events.forEach(function (ev) { renderLine(logEl, ev); });
    }
    if (!window.NexusStream) return;
    NexusStream.subscribe(function (msg) {
      if (msg.source !== "preservation") return;
      var ev = fromPayload(msg);
      renderLine(logEl, ev);
      events.push(ev);
      store(events);
    });
  }

  window.NexusPreservation = { init: init };
})();

/* ---- Metrics in-place refresh (B14) --------------------------------------
   The metrics-kv board is server-rendered once at page load; this keeps it
   live from the server-pushed `nexus.snapshot` event (task 2.2) rather than
   polling /diagnostics/metrics.json on its own timer. */
(function () {
  function render(kvEl, metrics) {
    if (!kvEl || !metrics) return;
    kvEl.innerHTML = "";
    Object.keys(metrics).forEach(function (key) {
      var dt = document.createElement("dt");
      dt.textContent = key;
      var dd = document.createElement("dd");
      var v = metrics[key];
      dd.textContent = (v && typeof v === "object") ? JSON.stringify(v) : String(v);
      kvEl.appendChild(dt);
      kvEl.appendChild(dd);
    });
  }

  function attach() {
    var kvEl = document.getElementById("metrics-kv");
    if (!kvEl || !window.NexusStream) return;
    NexusStream.subscribe(function (msg) {
      if (msg && msg.source === "nexus" && msg.type === "nexus.snapshot") {
        var p = msg.payload || {};
        if (p.metrics) render(kvEl, p.metrics);
      }
    });
  }

  window.NexusMetrics = { attach: attach };
})();

/* ---- Relative "Xs ago" timestamps (B7) ----------------------------------- */
(function () {
  function relative(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return null;
    var secs = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (secs < 60) return secs + "s ago";
    var mins = Math.round(secs / 60);
    if (mins < 60) return mins + "m ago";
    var hrs = Math.round(mins / 60);
    return hrs + "h ago";
  }

  function refresh() {
    document.querySelectorAll(".checked-at[data-at]").forEach(function (el) {
      var rel = relative(el.dataset.at);
      if (rel) el.textContent = "checked " + rel;
    });
  }

  function attach() {
    refresh();
    if (window.NexusVisibility) NexusVisibility.pausable(refresh, 5000);
    else setInterval(refresh, 5000);
  }

  // Auto-run on load so the health board shows relative times without explicit wiring.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", attach);
  } else {
    attach();
  }
  window.NexusRelTime = { attach: attach };
})();

/* ---- Live cycle vitals (run identity / pacing / modules / banner / awake) --
   The cycle/run-identity/pacing/module panels are server-rendered ONCE at page
   load. Without this, opening Nexus BEFORE starting the cycle leaves those
   panels frozen on their dead "not running" snapshot forever — the operator
   has to reload the page. This refreshes them in place: a ONE-SHOT fetch of
   /diagnostics/metrics.json + /diagnostics/health.json for the first paint,
   then the server-pushed `nexus.snapshot` event (over the shared diagnostics
   SSE — task 2.2) keeps them live thereafter, no poll loop. Per-module
   activity + the awake/sleeping pill are driven from the same shared stream.
   All fields are non-content operational metadata.

   DATA CONTRACT (kept in sync with the backend + asserted in
   tests/test_nexus_observability.py):
     metrics.json : cycle_status, run_id, seed, git_sha, kaine_version,
                    supervision_mode, gate_checks, processing_rate_hz,
                    experiential_rate_hz
     health.json  : cycle_pacing{state,time_scale,target_rate_hz,
                    achieved_rate_hz,mean_tick_ms,mean_slip_ms,max_slip_ms,
                    overrunning,overrun_ticks,window_ticks},
                    admissibility{state,run_id,manifest_present,tick_index},
                    modules[]{name,enabled,initialized,capturing}
*/
(function () {
  var ACTIVE_WINDOW_MS = 6000;        // a module counts as "active" if it
  var lastSeen = {};                   // published within this window

  // ---- status chip inputs (four-state, derived live) ------------------------
  // The left-rail chip reflects the REAL cycle state, not a hardwired
  // awake/sleeping binary that read "awake" even with no cycle running. Three
  // independent inputs feed it; whenever any changes we recompute one chip
  // state by priority OFFLINE > FROZEN > SLEEPING > AWAKE.
  //   running  — cycle_status === "running" (from the pushed metrics snapshot)
  //   frozen   — operator freeze / experiential-loop paused (metrics.frozen)
  //   sleeping — Hypnos asleep (hypnos.sleep.started/completed events)
  // All three are metadata-only; none carries cognitive content.
  var chip = { running: false, frozen: false, sleeping: false };
  var lastChipState = null;

  var CHIP_LABELS = {
    offline: "offline",
    frozen: "frozen",
    sleeping: "sleeping",
    awake: "awake",
  };
  var CHIP_CLASSES = ["offline", "frozen", "sleeping", "awake"];

  function computeChipState() {
    if (!chip.running) return "offline";   // no cognitive cycle → OFFLINE
    if (chip.frozen) return "frozen";       // running but experiential loop paused
    if (chip.sleeping) return "sleeping";   // running + Hypnos asleep
    return "awake";                          // running, not frozen, not sleeping
  }

  function renderChip() {
    var state = computeChipState();
    if (state === lastChipState) return;
    lastChipState = state;
    var b = document.getElementById("sleep-badge");
    if (!b) return;
    CHIP_CLASSES.forEach(function (c) { b.classList.toggle(c, c === state); });
    b.textContent = CHIP_LABELS[state];
  }

  // Input setters — each records one input and recomputes the single chip
  // state. Called from the metrics snapshot (running/frozen) and the hypnos
  // sleep/wake events (sleeping).
  function setSleep(isSleeping) { chip.sleeping = !!isSleeping; renderChip(); }
  function setRunning(isRunning) { chip.running = !!isRunning; renderChip(); }
  function setFrozen(isFrozen) { chip.frozen = !!isFrozen; renderChip(); }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function show(node, visible) { if (node) { if (visible) node.removeAttribute("hidden"); else node.setAttribute("hidden", ""); } }

  async function fetchJson(url) {
    try {
      var r = await fetch(url, { cache: "no-store" });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) { return null; }
  }

  // ---- cycle-running banner + live-only panels ------------------------------
  function renderBanner(metrics) {
    var running = metrics && metrics.cycle_status === "running";
    show(document.getElementById("cycle-not-running"), !running);
    show(document.getElementById("cycle-charts"), running);
    show(document.getElementById("metrics"), running);
    // Feed the status chip: running-state and the operator-freeze flag both
    // ride the metrics snapshot (metadata-only). `frozen` is only meaningful
    // while running, but setFrozen stores it either way — computeChipState
    // gates it behind `running` anyway (OFFLINE wins).
    setRunning(running);
    if (metrics && "frozen" in metrics) setFrozen(!!metrics.frozen);
  }

  // ---- run identity & supervision ------------------------------------------
  function renderRunIdentity(metrics, health) {
    var body = document.getElementById("run-identity-body");
    if (!body || !metrics) return;
    var admiss = health ? health.admissibility : null;
    var frag = document.createDocumentFragment();

    var mode = metrics.supervision_mode;
    if (mode === "research") {
      var badge = el("div", "supervision-badge supervision-badge--research");
      badge.setAttribute("role", "status");
      badge.appendChild(el("strong", null, "RESEARCH MODE"));
      badge.appendChild(el("span", "muted", "unsupervised — gated by the autonomous safety net"));
      var checks = metrics.gate_checks;
      if (checks && typeof checks === "object") {
        var ul = el("ul", "gate-checks");
        Object.keys(checks).forEach(function (name) {
          var ok = !!checks[name];
          var li = el("li", "gate-check " + (ok ? "ok" : "fail"),
            (ok ? "✓ " : "✗ ") + name.replace(/_/g, " "));
          ul.appendChild(li);
        });
        badge.appendChild(ul);
      }
      frag.appendChild(badge);
    } else if (mode === "operator") {
      var ob = el("div", "supervision-badge supervision-badge--operator");
      ob.setAttribute("role", "status");
      ob.appendChild(el("strong", null, "operator-supervised"));
      frag.appendChild(ob);
    }

    if (metrics.run_id) {
      var dl = el("dl", "kv");
      function row(k, v) { dl.appendChild(el("dt", null, k)); dl.appendChild(el("dd", "mono", v)); }
      row("run id", metrics.run_id);
      row("seed", metrics.seed);
      row("git sha", metrics.git_sha || "—");
      row("version", metrics.kaine_version || "—");
      frag.appendChild(dl);
    } else {
      frag.appendChild(el("p", "muted", "No run identity yet — the cycle has not minted a run context."));
    }

    if (admiss && admiss.state) {
      var p = el("p");
      p.appendChild(document.createTextNode("admissibility: "));
      p.appendChild(el("span", "chip " + admiss.state, String(admiss.state).replace(/-/g, " ")));
      var detail = " manifest " + (admiss.manifest_present ? "present" : "absent") +
        " · last tick " + (admiss.tick_index !== null && admiss.tick_index !== undefined ? admiss.tick_index : "—");
      p.appendChild(el("span", "muted", detail));
      frag.appendChild(p);
    }

    body.replaceChildren(frag);
  }

  // ---- cycle pacing (time scale) -------------------------------------------
  function fmt(v, digits, unit) {
    if (v === null || v === undefined) return "—";
    var n = (typeof v === "number") ? v.toFixed(digits) : v;
    return n + (unit || "");
  }
  function renderPacing(cp) {
    var body = document.getElementById("cycle-pacing-body");
    if (!body) return;
    var frag = document.createDocumentFragment();
    if (!cp) {
      frag.appendChild(el("p", "chart-empty", "Cycle-pacing status unavailable."));
      body.replaceChildren(frag);
      return;
    }
    var chip = cp.state === "holding" ? "up" : (cp.state === "throttling" ? "degraded" : "unknown");
    var p = el("p");
    p.appendChild(document.createTextNode("state: "));
    p.appendChild(el("span", "chip " + chip, cp.state));
    if (cp.overrunning) p.appendChild(el("span", "muted", " overrunning — honest shortfall"));
    frag.appendChild(p);

    var dl = el("dl", "kv");
    function row(k, v) { dl.appendChild(el("dt", null, k)); dl.appendChild(el("dd", null, v)); }
    row("time scale", (cp.time_scale !== null && cp.time_scale !== undefined ? cp.time_scale : "—") + "×");
    row("target rate", fmt(cp.target_rate_hz, 3, " Hz"));
    row("achieved rate", fmt(cp.achieved_rate_hz, 3, " Hz"));
    row("mean tick", fmt(cp.mean_tick_ms, 1, " ms"));
    row("mean slip", fmt(cp.mean_slip_ms, 1, " ms"));
    row("max slip", fmt(cp.max_slip_ms, 1, " ms"));
    row("overrunning", cp.overrunning ? "yes" : "no");
    if (cp.overrun_ticks !== null && cp.overrun_ticks !== undefined) {
      row("overrun ticks", cp.overrun_ticks + " / " +
        (cp.window_ticks !== null && cp.window_ticks !== undefined ? cp.window_ticks : "—"));
    }
    frag.appendChild(dl);
    body.replaceChildren(frag);
  }

  // ---- module grid (live activity) -----------------------------------------
  function renderModules(modules) {
    var grid = document.getElementById("module-grid");
    if (!grid || !Array.isArray(modules)) return;
    show(document.getElementById("module-grid-heading"), modules.length > 0);
    var now = Date.now();
    var frag = document.createDocumentFragment();
    modules.forEach(function (m) {
      var recentlyActive = lastSeen[m.name] && (now - lastSeen[m.name] < ACTIVE_WINDOW_MS);
      // A module publishing on the bus is live even if runtime.json's module
      // list lagged a tick — never paint a publishing module "idle".
      var cls = "module-cell ";
      var state;
      if (!m.enabled) { cls += "off"; state = "disabled"; }
      else if (m.capturing) { cls += "capturing"; state = "🔴 capturing"; }
      else if (m.initialized && recentlyActive) { cls += "on active"; state = "active"; }
      else if (m.initialized) { cls += "on"; state = "running"; }
      else if (recentlyActive) { cls += "on active"; state = "active"; }
      else { cls += "off"; state = "idle"; }
      var cell = el("div", cls);
      cell.dataset.module = m.name;
      cell.appendChild(el("span", "mname", m.name));
      cell.appendChild(el("span", "mstate", state));
      frag.appendChild(cell);
    });
    grid.replaceChildren(frag);
  }

  // ---- shared diagnostics SSE: per-module activity + sleep lifecycle,
  // plus the server-pushed nexus.snapshot (task 2.2) that replaces this
  // panel's own metrics.json/health.json poll loop. ------------------------
  function renderSnapshot(metrics, health) {
    if (metrics) { renderBanner(metrics); renderRunIdentity(metrics, health); }
    if (health) { renderPacing(health.cycle_pacing); renderModules(health.modules); }
  }

  function attachStream() {
    if (!window.NexusStream) return;
    NexusStream.subscribe(function (msg) {
      if (!msg) return;
      if (msg.source) lastSeen[msg.source] = Date.now();
      if (msg.source === "hypnos") {
        if (msg.type === "hypnos.sleep.started") setSleep(true);
        else if (msg.type === "hypnos.sleep.completed") setSleep(false);
      }
      // The server pushes a combined {metrics, health} snapshot every few
      // seconds (>= the health cache TTL) over this SAME stream — no
      // separate poll loop needed to keep these panels live.
      if (msg.source === "nexus" && msg.type === "nexus.snapshot") {
        var p = msg.payload || {};
        renderSnapshot(p.metrics, p.health);
      }
    });
  }

  // One-shot fetch for the FIRST paint, before the first periodic push
  // arrives (up to a few seconds) — NOT a poll loop (see init()).
  async function poll() {
    var metrics = await fetchJson("/diagnostics/metrics.json");
    var health = await fetchJson("/diagnostics/health.json");
    renderSnapshot(metrics, health);
  }

  function init() {
    attachStream();
    poll();
  }

  window.NexusVitals = { init: init, _poll: poll };
})();

/* ---- Perception PiP (entity view) + audio mute -----------------------------
   Over the visualizer's bottom-right: a live picture-in-picture of WHAT THE
   ENTITY SEES, plus a MUTE control for what it HEARS.

   - The video PiP only appears under the dev override (perception.json
     `preview_enabled`) AND when a frame actually exists — the <img> hides itself
     on a 404 (dev flag off / no frame yet / capture stopped), so nothing shows
     unless there is a real live frame to show. No raw frame is ever stored; the
     backend serves a single overwritten in-memory JPEG.
   - The mute control always works: it flips the audio desired-state via the
     existing POST /diagnostics/perception/toggle {surface:"audio",...} endpoint
     (the virtual-locus gate mutes the feed). It reflects the current state and
     confirms before UN-muting (turning listening back on), mirroring the privacy
     confirmation on the main perception toggles.
*/
(function () {
  var VIDEO_MS = 700;
  var AUDIO_MS = 400;
  var previewEnabled = false;
  var audioDesired = false;

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function () { return null; });
  }

  function setMute(desiredOn) {
    audioDesired = !!desiredOn;
    var btn = document.getElementById("perception-mute");
    if (!btn) return;
    // aria-pressed=true means MUTED (listening off).
    btn.setAttribute("aria-pressed", desiredOn ? "false" : "true");
    btn.textContent = desiredOn ? "🔊" : "🔇";
    btn.title = desiredOn ? "Mute what the entity hears" : "Unmute — let the entity hear again";
  }

  function attachMute() {
    var hud = document.getElementById("perception-hud");
    var btn = document.getElementById("perception-mute");
    if (!hud || !btn) return;
    hud.removeAttribute("hidden");     // the mute control is always available
    btn.addEventListener("click", async function () {
      var turningOn = !audioDesired;   // currently muted → this UN-mutes
      if (turningOn &&
          !confirm("Unmute — let KAINE hear continuously again? Nothing is saved to disk.")) {
        return;
      }
      btn.disabled = true;
      try {
        var r = await fetch("/diagnostics/perception/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ surface: "audio", active: turningOn }),
        });
        if (r.ok) {
          var data = null;
          try { data = await r.json(); } catch (e) { /* ignore */ }
          setMute(data ? !!data.audio_live_desired : turningOn);
        }
      } catch (e) { /* leave state as-is */ }
      finally { btn.disabled = false; }
    });
  }

  function pollVideo() {
    var pip = document.getElementById("perception-pip");
    var img = document.getElementById("perception-pip-img");
    if (!pip || !img) return;
    if (!previewEnabled) { pip.setAttribute("hidden", ""); return; }
    // Cache-busted single-frame fetch; show on load, hide on 404/error.
    var url = "/diagnostics/perception/preview/video?t=" + Date.now();
    img.onload = function () { pip.removeAttribute("hidden"); };
    img.onerror = function () { pip.setAttribute("hidden", ""); };
    img.src = url;
  }

  async function pollAudioMeter() {
    var fill = document.getElementById("perception-meter-fill");
    if (!fill || !previewEnabled) return;
    var snap = await fetchJson("/diagnostics/perception/preview/audio");
    var level = snap && typeof snap.level === "number" ? snap.level : 0;
    fill.style.width = Math.max(0, Math.min(1, level)) * 100 + "%";
  }

  async function refreshState() {
    var snap = await fetchJson("/diagnostics/perception.json");
    if (!snap) return;
    previewEnabled = !!snap.preview_enabled;
    setMute(!!snap.audio_live_desired);
  }

  async function init() {
    attachMute();
    await refreshState();
    pollVideo();
    if (window.NexusVisibility) {
      // These three intervals fetch a frame / JSON snapshot each tick — a
      // backgrounded tab must not keep polling them (task 1.4).
      NexusVisibility.pausable(refreshState, 3000);
      NexusVisibility.pausable(pollVideo, VIDEO_MS);
      NexusVisibility.pausable(pollAudioMeter, AUDIO_MS);
    } else {
      setInterval(refreshState, 3000);
      setInterval(pollVideo, VIDEO_MS);
      setInterval(pollAudioMeter, AUDIO_MS);
    }
  }

  window.NexusPreview = { init: init };
})();
