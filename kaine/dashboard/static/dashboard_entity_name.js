// SPDX-License-Identifier: LicenseRef-CAL-0.5
// Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

(function () {
  "use strict";

  var URL = "/diagnostics/entity-name.json";
  var POLL_MS = 10000;

  function apply(name) {
    if (typeof name !== "string" || !name) {
      return;
    }
    var els = document.querySelectorAll("[data-entity-name], #entity-name");
    var old = els.length ? els[0].textContent : "";
    // The console title is "<name> — dashboard console"; other pages carry no name.
    if (old && old !== name && document.title.indexOf(old + " ") === 0) {
      document.title = name + document.title.slice(old.length);
    }
    for (var i = 0; i < els.length; i++) {
      if (els[i].textContent !== name) {
        els[i].textContent = name;
      }
    }
  }

  function poll() {
    fetch(URL, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) { apply(data.name); } })
      .catch(function () {});
  }

  function start() {
    poll();
    setInterval(poll, POLL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
