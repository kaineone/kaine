// SPDX-License-Identifier: LicenseRef-CAL-0.2
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
  var STATUS_URL = "/diagnostics/birth.json";
  var ACK_URL = "/diagnostics/birth/ack";
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

  function render(data) {
    var panel = byId(PANEL_ID);
    if (!panel) {
      return;
    }
    var development = data && data.development;
    if (!development) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;

    setText(STAGE_ID, development.stage);
    var lived = development.lived_seconds;
    if (typeof lived === "number") {
      setText(LIVED_ID, (lived / 3600).toFixed(1));
    } else {
      setText(LIVED_ID, "");
    }
    setText(SLEEPS_ID, development.sleep_count);
    setText(PASSES_ID, development.consolidation_passes);

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
          throw new Error("birth status fetch failed");
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
              showAckMessage("birth acknowledged");
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
      window.NexusVisibility &&
      typeof window.NexusVisibility.pausable === "function"
    ) {
      window.NexusVisibility.pausable(refresh, POLL_MS);
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

  window.NexusBirth = {
    refresh: refresh,
    attachAck: attachAck,
    render: render,
  };
})();
