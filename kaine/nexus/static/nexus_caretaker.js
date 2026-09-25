// SPDX-License-Identifier: LicenseRef-CAL-0.2
// Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

(function () {
  "use strict";

  var BANNER_ID = "caretaker-banner";
  var SINCE_ID = "caretaker-banner-since";
  var ACK_ID = "caretaker-ack";
  var MSG_ID = "caretaker-ack-msg";
  var STATUS_URL = "/diagnostics/caretaker.json";
  var ACK_URL = "/diagnostics/caretaker/ack";
  var POLL_MS = 15000;

  function byId(id) {
    return document.getElementById(id);
  }

  function showMessage(text) {
    var msg = byId(MSG_ID);
    if (msg) {
      msg.textContent = text;
    }
  }

  function refresh() {
    fetch(STATUS_URL, { cache: "no-store" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("caretaker status fetch failed");
        }
        return resp.json();
      })
      .then(function (data) {
        var banner = byId(BANNER_ID);
        var since = byId(SINCE_ID);
        var ackBtn = byId(ACK_ID);
        if (!banner) {
          return;
        }
        if (data && data.pending) {
          banner.hidden = false;
          if (since) {
            since.textContent = " since " + (data.started_at || "");
          }
          if (ackBtn) {
            ackBtn.dataset.startId = data.start_id || "";
          }
        } else {
          banner.hidden = true;
          if (since) {
            since.textContent = "";
          }
          if (ackBtn) {
            ackBtn.dataset.startId = "";
          }
        }
      })
      .catch(function () {
        // Leave the banner in its current state on transient errors.
      });
  }

  function attach() {
    var ackBtn = byId(ACK_ID);
    if (!ackBtn) {
      return;
    }
    ackBtn.addEventListener("click", function () {
      var startId = ackBtn.dataset.startId;
      if (!startId) {
        return;
      }
      ackBtn.disabled = true;
      fetch(ACK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_id: startId }),
      })
        .then(function (resp) {
          showMessage(resp.ok ? "acknowledged" : "failed");
        })
        .catch(function () {
          showMessage("failed");
        })
        .then(function () {
          ackBtn.disabled = false;
          refresh();
        });
    });
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
    attach();
    refresh();
    scheduleRefresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.NexusCaretaker = { refresh: refresh, attach: attach };
})();
