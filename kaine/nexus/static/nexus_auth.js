/* SPDX-License-Identifier: LicenseRef-CAL-0.2 */
/* Copyright (c) 2026 Kaine.One <kaine.one@tuta.com> */
/*
 * Why localStorage + header?
 *
 * On localhost the browser shares cookies across ports on the same host, so the
 * HttpOnly session cookie by itself would authenticate any origin on the same
 * host. The session key is therefore kept only in origin-scoped localStorage
 * and sent explicitly via the X-Nexus-Session-Key header for state-changing
 * requests. The cookie is still required, but it alone must not authorize
 * mutations.
 */

(function () {
  "use strict";

  // Guard against double-installation if the script is included more than once.
  if (window.__nexusAuthInstalled) {
    return;
  }
  window.__nexusAuthInstalled = true;

  var STORAGE_KEY = "kaine.nexus.sessionKey";

  // Clock hook for tests; defaults to the real clock.
  if (typeof window.__nexusAuthNow !== "function") {
    window.__nexusAuthNow = function () {
      return Date.now();
    };
  }
  function nexusNow() {
    return window.__nexusAuthNow();
  }

  function getStoredKey() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStoredKey(value) {
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch (e) {
      // Storage unavailable; leave the key unstored.
    }
  }

  function clearStoredKey() {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      // Ignore storage failures.
    }
  }

  // ---------------------------------------------------------------------------
  // Login page handling
  // ---------------------------------------------------------------------------

  function initLoginForm() {
    var form = document.getElementById("nexus-login-form");
    if (!form) {
      return;
    }

    var errorEl = document.getElementById("nexus-login-error");
    var submitBtn = form.querySelector(
      'button[type="submit"], input[type="submit"]'
    );

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var tokenInput = document.getElementById("nexus-login-token");
      var token = tokenInput ? tokenInput.value : "";

      clearStoredKey();
      if (errorEl) {
        errorEl.textContent = "";
      }
      if (submitBtn) {
        submitBtn.disabled = true;
      }

      fetch(form.action || "/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded"
        },
        body: "token=" + encodeURIComponent(token)
      })
        .then(function (response) {
          if (response.status === 200) {
            return response.json().then(function (data) {
              setStoredKey(data.session_key);

              var target = "/";
              if (
                typeof data.redirect === "string" &&
                data.redirect.charAt(0) === "/" &&
                data.redirect.indexOf("//") !== 0
              ) {
                target = data.redirect;
              }
              location.assign(target);
            });
          }

          if (errorEl) {
            if (response.status === 401) {
              errorEl.textContent = "Invalid token.";
            } else if (response.status === 429) {
              errorEl.textContent = "Too many attempts; wait and try again.";
            } else if (response.status === 503) {
              errorEl.textContent =
                "No operator token is configured on the server.";
            } else {
              errorEl.textContent = "Could not reach Nexus.";
            }
          }
        })
        .catch(function () {
          if (errorEl) {
            errorEl.textContent = "Could not reach Nexus.";
          }
        })
        .finally(function () {
          if (submitBtn) {
            submitBtn.disabled = false;
          }
        });
    });
  }

  function initLogoutButton() {
    var btn = document.getElementById("nexus-logout");
    if (!btn) {
      return;
    }
    btn.addEventListener("click", function () {
      window.NexusAuth.logout();
    });
  }

  function initUI() {
    initLoginForm();
    initLogoutButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initUI);
  } else {
    initUI();
  }

  // ---------------------------------------------------------------------------
  // Global fetch wrapper
  // ---------------------------------------------------------------------------

  var originalFetch = window.fetch;

  function getMethod(input, init) {
    if (init && init.method) {
      return String(init.method).toUpperCase();
    }
    if (typeof Request !== "undefined" && input instanceof Request) {
      return input.method.toUpperCase();
    }
    return "GET";
  }

  function getRequestUrl(input) {
    var urlString;
    if (typeof Request !== "undefined" && input instanceof Request) {
      urlString = input.url;
    } else if (input instanceof URL) {
      urlString = input.href;
    } else {
      urlString = String(input);
    }
    return new URL(urlString, location.href);
  }

  function buildHeaders(input, init) {
    var headers = new Headers();

    if (typeof Request !== "undefined" && input instanceof Request) {
      input.headers.forEach(function (value, name) {
        headers.set(name, value);
      });
    }

    if (init && init.headers) {
      var provided = init.headers;
      if (provided instanceof Headers) {
        provided.forEach(function (value, name) {
          headers.set(name, value);
        });
      } else if (Array.isArray(provided)) {
        provided.forEach(function (pair) {
          if (pair && pair.length >= 2) {
            headers.set(String(pair[0]), String(pair[1]));
          }
        });
      } else if (provided && typeof provided === "object") {
        Object.keys(provided).forEach(function (name) {
          headers.set(name, provided[name]);
        });
      }
    }

    return headers;
  }

  function cloneInitWithHeaders(init, headers) {
    var nextInit = {};
    if (init) {
      for (var key in init) {
        if (Object.prototype.hasOwnProperty.call(init, key)) {
          nextInit[key] = init[key];
        }
      }
    }
    nextInit.headers = headers;
    return nextInit;
  }

  window.fetch = function nexusFetch(input, init) {
    var method = getMethod(input, init);
    var url = getRequestUrl(input);
    var key = getStoredKey();
    var nextInit = init;

    if (
      key &&
      url.origin === location.origin &&
      method !== "GET" &&
      method !== "HEAD" &&
      method !== "OPTIONS"
    ) {
      var headers = buildHeaders(input, init);
      headers.set("X-Nexus-Session-Key", key);
      nextInit = cloneInitWithHeaders(init, headers);
    }

    return originalFetch.call(window, input, nextInit).then(function (response) {
      if (
        response.status === 401 &&
        url.origin === location.origin &&
        !url.pathname.startsWith("/auth/") &&
        location.pathname !== "/login"
      ) {
        clearStoredKey();
        location.assign("/login");
      }
      return response;
    });
  };

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  window.NexusAuth = {
    logout: function () {
      fetch("/auth/logout", { method: "POST" })
        .then(function () {
          clearStoredKey();
          location.assign("/login");
        })
        .catch(function () {
          clearStoredKey();
          location.assign("/login");
        });
    },

    hasSessionKey: function () {
      return !!getStoredKey();
    }
  };

  // ---------------------------------------------------------------------------
  // EventSource wrapper — probes on terminal errors so a expired session does
  // not leave diagnostics silently "reconnecting" forever.
  // ---------------------------------------------------------------------------

  if (typeof window.EventSource !== "undefined" && window.EventSource) {
    var OriginalEventSource = window.EventSource;

    class NexusEventSource extends OriginalEventSource {
      constructor(...args) {
        super(...args);
        this.__nexusErrors = 0;
        this.__nexusLastProbe = null;
        this.__nexusProbing = false;
        var self = this;
        OriginalEventSource.prototype.addEventListener.call(
          this,
          "error",
          function (event) {
            self.__nexusOnError(event);
          }
        );
      }

      __nexusOnError(event) {
        var now = nexusNow();
        this.__nexusErrors += 1;
        if (
          this.readyState === OriginalEventSource.CLOSED ||
          this.__nexusErrors >= 3
        ) {
          this.__nexusMaybeProbe(now);
        }
      }

      __nexusMaybeProbe(now) {
        if (this.__nexusProbing) {
          return;
        }
        if (typeof this.__nexusLastProbe === "number" && now - this.__nexusLastProbe < 30000) {
          return;
        }
        this.__nexusLastProbe = now;
        this.__nexusProbing = true;
        var self = this;
        fetch("/diagnostics/perception.json", { cache: "no-store" })
          .catch(function () {})
          .finally(function () {
            self.__nexusProbing = false;
          });
      }
    }

    ["CONNECTING", "OPEN", "CLOSED"].forEach(function (name) {
      if (typeof OriginalEventSource[name] !== "undefined") {
        NexusEventSource[name] = OriginalEventSource[name];
      }
    });

    window.EventSource = NexusEventSource;
  }
})();
