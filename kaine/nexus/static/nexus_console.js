// SPDX-License-Identifier: LicenseRef-CAL-0.2
// Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
//
// Console-only behaviours layered on the server-rendered dashboard:
//   NexusFlow   — newspaper column flow: when a section spills into the next
//                 column, inject a "▸ … (continued)" marker so the continuation
//                 reads as part of the same section instead of a new one.
// The console is a single, scroll-free screen; sections flow across columns
// rather than scrolling, so the continuation marker is how a long section stays
// legible. Pure presentation — it reads layout geometry and adds marker nodes,
// touching no data.
(function () {
  "use strict";

  var NexusFlow = {
    _raf: 0,

    // Distinct left-x of every *visible* flowing card == the column starts.
    _columns: function (page) {
      var xs = {};
      var cards = page.querySelectorAll(".board__cards > *");
      for (var i = 0; i < cards.length; i++) {
        var r = cards[i].getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;          // collapsed/hidden
        if (cards[i].classList.contains("continued-marker")) continue;
        xs[Math.round(r.left)] = true;
      }
      return Object.keys(xs)
        .map(Number)
        .sort(function (a, b) { return a - b; });
    },

    _colIndex: function (cols, x) {
      var idx = 0;
      for (var i = 0; i < cols.length; i++) {
        if (x >= cols[i] - 2) idx = i;
      }
      return idx;
    },

    _clear: function (page) {
      var marks = page.querySelectorAll(".continued-marker");
      for (var i = 0; i < marks.length; i++) marks[i].remove();
    },

    run: function () {
      var page = document.querySelector(".page");
      if (!page) return;
      this._clear(page);
      var cols = this._columns(page);
      if (cols.length < 2) return;                              // single column — nothing spills

      var boards = page.querySelectorAll(".board");
      for (var b = 0; b < boards.length; b++) {
        var titleEl = boards[b].querySelector(".board__title");
        var title = (titleEl ? titleEl.textContent : "section")
          .trim()
          .replace(/^[▸\s]+/, "");
        var cards = boards[b].querySelectorAll(".board__cards > *");
        var prevCol = null;
        for (var c = 0; c < cards.length; c++) {
          var card = cards[c];
          if (card.classList.contains("continued-marker")) continue;
          var rect = card.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;  // collapsed board
          var ci = this._colIndex(cols, Math.round(rect.left));
          if (prevCol !== null && ci > prevCol) {
            var m = document.createElement("div");
            m.className = "continued-marker";
            m.setAttribute("aria-hidden", "true");
            m.textContent = "▸ " + title + " (continued)";
            card.parentNode.insertBefore(m, card);
          }
          prevCol = ci;
        }
      }
    },

    schedule: function () {
      var self = this;
      if (self._raf) cancelAnimationFrame(self._raf);
      self._raf = requestAnimationFrame(function () {
        self._raf = requestAnimationFrame(function () { self.run(); });
      });
    },

    init: function () {
      var self = this;
      self.schedule();
      var t = 0;
      window.addEventListener("resize", function () {
        clearTimeout(t);
        t = setTimeout(function () { self.schedule(); }, 120);
      });
      // Re-flow when a collapsed section is opened/closed (its cards appear).
      document.querySelectorAll(".page .board").forEach(function (board) {
        board.addEventListener("toggle", function () { self.schedule(); });
      });
    },
  };

  window.NexusFlow = NexusFlow;

  // ---- NexusSections -----------------------------------------------------
  // Closed sections leave the screen; their rail button summons them back. The
  // section slides IN FROM ITS BUTTON and expands into place (a FLIP transform:
  // it starts shrunk at the button's position and grows to its layout slot) —
  // an LCARS-style entrance. Dismissing reverses it: the section shrinks back
  // toward the button and leaves. Motion-gated.
  var NexusSections = {
    _btn: function (id) { return document.querySelector('.rail__seg[data-board="' + id + '"]'); },
    _reduced: function () {
      return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    },
    isOpen: function (board) { return !!board && !board.classList.contains("board--closed"); },
    _sync: function (board) {
      var btn = this._btn(board.id);
      if (btn) btn.classList.toggle("is-active", this.isOpen(board));
    },
    // Summon a section. The SHOW is a guaranteed class toggle; the slide-in is a
    // cosmetic CSS animation layered on top that can never leave the panel hidden.
    summon: function (board) {
      if (!board || this.isOpen(board)) return;
      board.classList.remove("board--closed");        // shown — guaranteed
      if (!this._reduced()) {
        board.classList.remove("board--leave");
        board.classList.add("board--enter");          // cosmetic slide-in
        setTimeout(function () { board.classList.remove("board--enter"); }, 480);
      }
      this._sync(board);
      if (window.NexusFlow) NexusFlow.schedule();
    },

    // Dismiss a section. The HIDE is guaranteed by a timeout fallback even if the
    // leave animation's animationend never fires.
    dismiss: function (board) {
      if (!board || !this.isOpen(board)) return;
      var self = this;
      var hide = function () {
        board.classList.remove("board--leave");
        board.classList.add("board--closed");         // hidden — guaranteed
        self._sync(board);
        if (window.NexusFlow) NexusFlow.schedule();
      };
      if (this._reduced()) { hide(); return; }
      board.classList.remove("board--enter");
      board.classList.add("board--leave");
      var done = false;
      var fin = function () { if (done) return; done = true; board.removeEventListener("animationend", onEnd); hide(); };
      var onEnd = function (e) { if (e.target === board) fin(); };
      board.addEventListener("animationend", onEnd);
      setTimeout(fin, 380);                            // fallback: always hides
    },

    toggle: function (id) {
      var board = document.getElementById(id);
      if (!board) return;
      if (this.isOpen(board)) this.dismiss(board); else this.summon(board);
    },
    summonById: function (id) { this.summon(document.getElementById(id)); },

    init: function () {
      var self = this;
      var btns = document.querySelectorAll(".rail__seg[data-board]");
      btns.forEach(function (btn) {
        var id = btn.getAttribute("data-board");
        var board = document.getElementById(id);
        if (board) self._sync(board);
        btn.addEventListener("click", function () {
          try { self.toggle(id); } catch (e) { if (window.console) console.error("toggle", id, e); }
        });
      });
    },
  };
  window.NexusSections = NexusSections;

  // ---- NexusReveal -------------------------------------------------------
  // Situational sections sit COLLAPSED until they matter. When a relevant event
  // arrives on the diagnostics stream, expand that section and briefly FLASH it
  // so the operator's eye is drawn to it — instead of hiding the information away
  // in a popup. With no entity running, no events arrive and everything stays
  // calmly collapsed (honest idle state).
  var NexusReveal = {
    // event signature -> board to surface. Welfare-protective + preservation
    // activity surfaces the welfare board; divergence surfaces the identity/
    // divergence board.
    _rules: [
      { test: function (m) { return m.source === "welfare" || /^welfare\./.test(m.type || ""); }, board: "board-welfare" },
      { test: function (m) { return m.source === "preservation" || /^preservation\./.test(m.type || ""); }, board: "board-welfare" },
      { test: function (m) { return /divergence|individuat/i.test(m.type || ""); }, board: "board-identity" },
    ],

    surface: function (id) {
      var board = document.getElementById(id);
      if (!board) return;
      // Summon the section in from its button (or just ensure it is open).
      if (window.NexusSections) window.NexusSections.summonById(id);
      else if (board.tagName === "DETAILS" && !board.open) board.open = true;
      board.classList.remove("board--flash");
      void board.offsetWidth;                            // restart the flash animation
      board.classList.add("board--flash");
      setTimeout(function () { board.classList.remove("board--flash"); }, 2200);
    },

    init: function () {
      if (!window.NexusStream) return;
      var self = this;
      // Ignore the backfill burst a stream replays on connect — only a NEW,
      // live event should expand+flash a section. Without this, any historical
      // welfare/preservation event would re-open the section on every load,
      // defeating the glanceable-collapse intent.
      var readyAt = Date.now() + 2500;
      NexusStream.subscribe(function (msg) {
        if (Date.now() < readyAt) return;
        if (!msg) return;
        for (var i = 0; i < self._rules.length; i++) {
          if (self._rules[i].test(msg)) { self.surface(self._rules[i].board); break; }
        }
      });
    },
  };
  window.NexusReveal = NexusReveal;


  // The console never scrolls vertically; when more sections are open than fit
  // the width, the vertical mouse wheel scrolls the horizontal overflow. An inner
  // vertically-scrollable element (a table, a capped log) gets the wheel first.
  // Below this width the console switches to a normal vertical-scroll layout
  // (see the mobile breakpoint in style.css) — the sideways wheel-hijack would
  // fight a touch/trackpad user trying to scroll DOWN a phone screen, so it is
  // disabled there (task 1.5).
  var MOBILE_BREAKPOINT_PX = 640;

  function initWheelScroll() {
    var page = document.querySelector(".page--console");
    if (!page) return;
    page.addEventListener("wheel", function (e) {
      if (window.matchMedia && window.matchMedia("(max-width: " + MOBILE_BREAKPOINT_PX + "px)").matches) return;
      if (page.scrollWidth <= page.clientWidth + 1) return;   // nothing to scroll sideways
      var dy = e.deltaY;
      if (!dy) return;
      for (var n = e.target; n && n !== page; n = n.parentElement) {
        if (n.scrollHeight > n.clientHeight + 1) {            // a vertical scroller…
          var atTop = n.scrollTop <= 0;
          var atBottom = n.scrollTop + n.clientHeight >= n.scrollHeight - 1;
          if (!((dy < 0 && atTop) || (dy > 0 && atBottom))) return;  // …that can still move
        }
      }
      page.scrollLeft += dy;
      e.preventDefault();
    }, { passive: false });
  }

  function boot() {
    // Each init is isolated so one failure can't strip the others' handlers
    // (e.g. a NexusFlow error must never disable the section toggles).
    try { initWheelScroll(); } catch (e) { if (window.console) console.error("initWheelScroll", e); }
    try { NexusSections.init(); } catch (e) { if (window.console) console.error("NexusSections.init", e); }
    try { NexusFlow.init(); } catch (e) { if (window.console) console.error("NexusFlow.init", e); }
    try { NexusReveal.init(); } catch (e) { if (window.console) console.error("NexusReveal.init", e); }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
