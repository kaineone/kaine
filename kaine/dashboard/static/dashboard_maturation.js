// SPDX-License-Identifier: LicenseRef-CAL-0.5
// Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

(function () {
  "use strict";

  var PANEL_ID = "development-panel";
  var STAGE_ID = "dev-stage";
  var LIVED_ID = "dev-lived";
  var SLEEPS_ID = "dev-sleeps";
  var PASSES_ID = "dev-passes";
  var READINESS_ID = "dev-readiness";
  var DECISION_ID = "dev-decision";
  var ACK_ID = "dev-ack";
  var ACK_START_ID = "dev-ack-start";
  var ACK_CONFIRM_ROW_ID = "dev-ack-confirm-row";
  var ACK_CONFIRM_ID = "dev-ack-confirm";
  var ACK_CANCEL_ID = "dev-ack-cancel";
  var ACK_MSG_ID = "dev-ack-msg";
  var WORLD_ID = "dev-world";
  var WORLD_VALUE_ID = "dev-world-value";
  var HEARING_ID = "dev-hearing";
  var HEARING_VALUE_ID = "dev-hearing-value";
  var FEED_HEARING_ID = "feed-hearing-stage";
  var PASSES_ROW_ID = "dev-passes-row";
  var CONSOLIDATION_NOT_REQUIRED_ID = "dev-consolidation-not-required";
  var STATUS_URL = "/diagnostics/maturation.json";
  var ACK_URL = "/diagnostics/maturation/ack";
  var POLL_MS = 5000;

  function byId(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    var el = byId(id);
    if (el) {
      el.textContent = text == null ? "" : String(text);
    }
  }

  function formatBand(low, high) {
    if (typeof low === "number" && typeof high === "number") {
      return low.toFixed(1) + " to " + high.toFixed(1) + " Hz";
    }
    if (low === null && typeof high === "number") {
      return "below " + high.toFixed(1) + " Hz";
    }
    return "open";
  }

  function formatHours(seconds) {
    return String(Math.round((seconds / 3600) * 10) / 10);
  }

  function formatDwell(hearing) {
    var dwell = hearing.dwell_seconds;
    var min = hearing.min_dwell_seconds;
    var max = hearing.max_dwell_seconds;
    if (
      typeof dwell !== "number" || typeof min !== "number" || typeof max !== "number" ||
      !isFinite(dwell) || !isFinite(min) || !isFinite(max)
    ) {
      return "";
    }
    return formatHours(dwell) + " h of " + formatHours(min) + " to " + formatHours(max) + " h";
  }

  function formatHearing(hearing) {
    if (!hearing || typeof hearing.stage !== "number") {
      return "";
    }
    var text = "stage " + hearing.stage + " of 4, " + formatBand(hearing.low_hz, hearing.high_hz);
    var dwell = hearing.stage < 4 ? formatDwell(hearing) : "";
    return dwell ? text + ", " + dwell : text;
  }

  function renderReadiness(readiness, readout) {
    var lines = [];
    if (readiness && Array.isArray(readiness.passed)) {
      readiness.passed.forEach(function (name) {
        var label = String(name);
        if (readout && Object.prototype.hasOwnProperty.call(readout, name)) {
          label = label + " (" + String(readout[name]) + ")";
        }
        lines.push("✓ " + label);
      });
    }
    if (readiness && Array.isArray(readiness.unmet)) {
      readiness.unmet.forEach(function (name) {
        var label = String(name);
        if (readout && Object.prototype.hasOwnProperty.call(readout, name)) {
          label = label + " (" + String(readout[name]) + ")";
        }
        lines.push("✗ " + label);
      });
    }
    if (readiness && Array.isArray(readiness.not_applicable)) {
      readiness.not_applicable.forEach(function (name) {
        lines.push("\u2013 " + String(name) + " (not applicable)");
      });
    }
    setText(READINESS_ID, lines.join("\n"));
  }

  function renderDecision(decision) {
    var el = byId(DECISION_ID);
    if (!el) {
      return;
    }
    if (!decision || !decision.action) {
      el.hidden = true;
      setText(DECISION_ID, "");
      return;
    }
    el.hidden = false;
    var text = "action: " + String(decision.action);
    if (decision.reason) {
      text += "\nreason: " + String(decision.reason);
    }
    setText(DECISION_ID, text);
  }

  function updateConsolidation(development) {
    var passesRow = byId(PASSES_ROW_ID);
    var notRequiredRow = byId(CONSOLIDATION_NOT_REQUIRED_ID);
    var conditions = development && development.conditions;
    if (conditions && typeof conditions === "object" && conditions.c2_consolidation_required === false) {
      setText(PASSES_ID, "");
      if (passesRow) {
        passesRow.hidden = true;
      }
      if (notRequiredRow) {
        notRequiredRow.hidden = false;
      }
    } else {
      setText(PASSES_ID, development ? development.consolidation_passes : "");
      if (passesRow) {
        passesRow.hidden = false;
      }
      if (notRequiredRow) {
        notRequiredRow.hidden = true;
      }
    }
  }

  function render(data) {
    var panel = byId(PANEL_ID);
    if (!panel) {
      return;
    }
    var development = data && data.development;
    var hearing = data && data.hearing;

    if (!development && !hearing) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;

    var hearingText = formatHearing(hearing);
    var hearingRow = byId(HEARING_ID);
    if (hearingRow) {
      hearingRow.hidden = !hearingText;
    }
    setText(HEARING_VALUE_ID, hearingText);
    setText(FEED_HEARING_ID, hearingText || "not reported");

    var worldRow = byId(WORLD_ID);
    if (worldRow) {
      if (development && typeof development.world === "string" && development.world !== "") {
        worldRow.hidden = false;
        setText(WORLD_VALUE_ID, development.world);
      } else {
        worldRow.hidden = true;
        setText(WORLD_VALUE_ID, "");
      }
    }

    if (!development) {
      setText(STAGE_ID, "");
      setText(LIVED_ID, "");
      setText(SLEEPS_ID, "");
      updateConsolidation(null);
      renderReadiness(null, null);
      renderDecision(null);
      return;
    }

    setText(STAGE_ID, development.stage);
    var lived = development.lived_seconds;
    if (typeof lived === "number") {
      setText(LIVED_ID, (lived / 3600).toFixed(1));
    } else {
      setText(LIVED_ID, "");
    }
    setText(SLEEPS_ID, development.sleep_count);
    updateConsolidation(development);

    renderReadiness(development.readiness, development.readout);
    renderDecision(development.decision);

    var ack = byId(ACK_ID);
    var confirmBtn = byId(ACK_CONFIRM_ID);
    if (ack) {
      if (data.pending) {
        ack.hidden = false;
        if (confirmBtn) {
          confirmBtn.dataset.requestId = data.request_id || "";
        }
      } else {
        ack.hidden = true;
        if (confirmBtn) {
          confirmBtn.dataset.requestId = "";
        }
      }
    }
  }

  function showAckMessage(text) {
    setText(ACK_MSG_ID, text);
  }

  function resetConfirm() {
    var startBtn = byId(ACK_START_ID);
    var confirmRow = byId(ACK_CONFIRM_ROW_ID);
    if (startBtn) {
      startBtn.hidden = false;
    }
    if (confirmRow) {
      confirmRow.hidden = true;
    }
  }

  function refresh() {
    fetch(STATUS_URL, { cache: "no-store" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("maturation status fetch failed");
        }
        return resp.json();
      })
      .then(render)
      .catch(function () {
        // Leave the panel in its current state on transient errors.
      });
  }

  function attachAck() {
    var startBtn = byId(ACK_START_ID);
    var cancelBtn = byId(ACK_CANCEL_ID);
    var confirmBtn = byId(ACK_CONFIRM_ID);

    if (startBtn) {
      startBtn.addEventListener("click", function () {
        startBtn.hidden = true;
        var confirmRow = byId(ACK_CONFIRM_ROW_ID);
        if (confirmRow) {
          confirmRow.hidden = false;
        }
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener("click", resetConfirm);
    }

    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        var requestId = confirmBtn.dataset.requestId;
        if (!requestId) {
          return;
        }
        confirmBtn.disabled = true;
        fetch(ACK_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request_id: requestId }),
        })
          .then(function (resp) {
            if (resp.ok) {
              showAckMessage("maturation acknowledged");
              resetConfirm();
              refresh();
              return;
            }
            return resp.json().then(function (body) {
              var detail = body && body.detail;
              showAckMessage("failed: " + (detail || "unknown error"));
            });
          })
          .catch(function () {
            showAckMessage("failed: network error");
          })
          .then(function () {
            confirmBtn.disabled = false;
          });
      });
    }
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
    attachAck();
    refresh();
    scheduleRefresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.DashboardMaturation = {
    refresh: refresh,
    attachAck: attachAck,
    render: render,
    formatBand: formatBand,
    formatHearing: formatHearing,
  };
})();
