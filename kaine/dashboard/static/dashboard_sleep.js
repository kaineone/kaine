// SPDX-License-Identifier: LicenseRef-CAL-0.5
// Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

(function () {
  "use strict";

  var STATUS_URL = "/diagnostics/sleep.json";
  var POLL_MS = 5000;

  var TRIGGER_LABELS = {
    fatigue: "fatigue",
    maintenance_request: "maintenance request",
    affect_regulation: "emotion regulation",
    state_cycle: "state-cycle rest",
    requested: "requested",
    backstop: "backstop (an hour awake)",
    developmental_rest: "developmental rest (earlier rule)",
    fatigue_or_backstop: "fatigue or backstop (not stated)"
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    var el = byId(id);
    if (el) {
      el.textContent = text == null ? "" : String(text);
    }
  }

  function setHidden(id, hidden) {
    var el = byId(id);
    if (el) {
      el.hidden = hidden;
    }
  }

  function isNumber(v) {
    return typeof v === "number" && isFinite(v);
  }

  function triggerLabel(trigger) {
    if (
      typeof trigger === "string" &&
      Object.prototype.hasOwnProperty.call(TRIGGER_LABELS, trigger)
    ) {
      return TRIGGER_LABELS[trigger];
    }
    return "not known";
  }

  function formatDuration(s) {
    if (!isNumber(s)) {
      return "n/a";
    }
    var total = Math.round(Math.max(0, s));
    if (total < 60) {
      return total + " s";
    }
    return Math.floor(total / 60) + " min " + (total % 60) + " s";
  }

  function timeOf(value) {
    var d = new Date(value);
    if (isNaN(d.getTime())) {
      return "n/a";
    }
    return d.toLocaleTimeString();
  }

  function renderSleep(data) {
    var sleep = data && data.sleep;
    setText("sleep-state", data && data.sleeping ? "asleep" : "awake");
    if (!sleep) {
      setText("sleep-trigger", "n/a");
      setText("sleep-started", "n/a");
      setText("sleep-duration", "n/a");
      setText("sleep-rest-length", "n/a");
      setHidden("sleep-aborted", true);
      return;
    }
    setText("sleep-trigger", triggerLabel(sleep.trigger));
    setText(
      "sleep-started",
      isNumber(sleep.started_at) ? timeOf(sleep.started_at * 1000) : "n/a"
    );
    if (sleep.asleep && isNumber(sleep.started_at)) {
      setText(
        "sleep-duration",
        formatDuration(Date.now() / 1000 - sleep.started_at) + " so far"
      );
    } else {
      setText("sleep-duration", formatDuration(sleep.duration_s));
    }
    setText(
      "sleep-rest-length",
      isNumber(sleep.rest_seconds) ? formatDuration(sleep.rest_seconds) : "n/a"
    );
    setHidden("sleep-aborted", !sleep.aborted);
  }

  function render(data) {
    renderSleep(data || {});
  }

  function refresh() {
    fetch(STATUS_URL, { cache: "no-store" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("sleep status fetch failed");
        }
        return resp.json();
      })
      .then(render)
      .catch(function () {
        // Leave the panel in its current state on transient errors.
      });
  }

  function scheduleRefresh() {
    if (
      window.DashboardVisibility &&
      typeof window.DashboardVisibility.pausable === "function"
    ) {
      window.DashboardVisibility.pausable(refresh, POLL_MS);
    } else {
      setInterval(refresh, POLL_MS);
    }
  }

  function init() {
    refresh();
    scheduleRefresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.DashboardSleep = {
    refresh: refresh,
    render: render,
    triggerLabel: triggerLabel,
    formatDuration: formatDuration
  };
})();
