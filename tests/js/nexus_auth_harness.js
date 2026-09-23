const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(ROOT, "kaine", "nexus", "static", "nexus_auth.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

const STORAGE_KEY = "kaine.nexus.sessionKey";

function makeElement(id, extras) {
  extras = extras || {};
  var handlers = {};
  var el = {
    id: id,
    textContent: "",
    value: "",
    disabled: false,
    addEventListener: function (type, fn) {
      handlers[type] = fn;
    },
    getHandler: function (type) {
      return handlers[type];
    },
    querySelector: function () {
      return null;
    }
  };
  for (var key in extras) {
    if (Object.prototype.hasOwnProperty.call(extras, key)) {
      el[key] = extras[key];
    }
  }
  return el;
}

function makeFakeEventSource() {
  var instances = [];
  function FakeES(url, options) {
    this.url = url;
    this.options = options;
    this.readyState = FakeES.CONNECTING;
    this._listeners = {};
    instances.push(this);
  }
  FakeES.CONNECTING = 0;
  FakeES.OPEN = 1;
  FakeES.CLOSED = 2;
  FakeES.instances = instances;
  FakeES.prototype.addEventListener = function (type, fn) {
    var list = this._listeners[type] || (this._listeners[type] = []);
    list.push(fn);
  };
  FakeES.prototype.removeEventListener = function (type, fn) {
    var list = this._listeners[type];
    if (!list) return;
    var idx = list.indexOf(fn);
    if (idx !== -1) list.splice(idx, 1);
  };
  FakeES.prototype.dispatchEvent = function (event) {
    var list = this._listeners[event.type];
    if (!list) return;
    for (var i = 0; i < list.length; i++) {
      list[i].call(this, event);
    }
  };
  FakeES.prototype.triggerError = function () {
    this.dispatchEvent({ type: "error", target: this, currentTarget: this });
  };
  return FakeES;
}

function makeSandbox(scenario) {
  var localStorageData = {};
  var localStorage = {
    getItem: function (k) {
      return Object.prototype.hasOwnProperty.call(localStorageData, k)
        ? localStorageData[k]
        : null;
    },
    setItem: function (k, v) {
      localStorageData[k] = String(v);
    },
    removeItem: function (k) {
      delete localStorageData[k];
    }
  };

  var assignTargets = [];
  var fetchCalls = [];

  var location = {
    origin: "http://127.0.0.1:8088",
    href: "http://127.0.0.1:8088/",
    pathname: "/",
    assign: function (target) {
      assignTargets.push(target);
    }
  };

  var elements = {};

  var document = {
    readyState: "complete",
    addEventListener: function () {},
    getElementById: function (id) {
      return elements[id] || null;
    }
  };

  var scriptedResponse = { status: 200, json: async function () { return {}; } };

  function fakeFetch(url, init) {
    fetchCalls.push({ url: url, init: init });
    return Promise.resolve(scriptedResponse);
  }

  var sandbox = {
    window: undefined,
    document: document,
    localStorage: localStorage,
    location: location,
    Headers: globalThis.Headers,
    Request: globalThis.Request,
    URL: globalThis.URL,
    Promise: globalThis.Promise,
    Date: globalThis.Date,
    console: globalThis.console,
    fetch: fakeFetch,
    encodeURIComponent: globalThis.encodeURIComponent,
    decodeURIComponent: globalThis.decodeURIComponent,
    _elements: elements,
    _localStorage: localStorageData,
    _assignTargets: assignTargets,
    _fetchCalls: fetchCalls,
    _setResponse: function (resp) {
      scriptedResponse = resp;
    }
  };

  sandbox.window = sandbox;

  if (scenario.setup) {
    scenario.setup(sandbox);
  }

  return sandbox;
}

function tick() {
  return new Promise(function (resolve) {
    setTimeout(resolve, 0);
  });
}

function runScript(sandbox) {
  vm.runInNewContext(source, sandbox, { filename: "nexus_auth.js" });
}

var scenarios = [
  {
    name: "login success",
    setup: function (sandbox) {
      var submitBtn = makeElement("nexus-submit", { disabled: false });
      var form = makeElement("nexus-login-form", {
        action: "/auth/login",
        querySelector: function () {
          return submitBtn;
        }
      });
      var tokenInput = makeElement("nexus-login-token", { value: "operator" });
      var errorEl = makeElement("nexus-login-error");

      sandbox._elements["nexus-login-form"] = form;
      sandbox._elements["nexus-login-token"] = tokenInput;
      sandbox._elements["nexus-login-error"] = errorEl;
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return { session_key: "K1", redirect: "/" };
        }
      });
    },
    run: async function (sandbox) {
      var form = sandbox.document.getElementById("nexus-login-form");
      var handler = form.getHandler("submit");
      if (!handler) {
        throw new Error("submit handler not captured");
      }
      handler({ preventDefault: function () {} });
      await tick();
      var key = sandbox.localStorage.getItem(STORAGE_KEY);
      if (key !== "K1") {
        throw new Error("expected session key K1, got " + key);
      }
      if (
        sandbox._assignTargets.length !== 1 ||
        sandbox._assignTargets[0] !== "/"
      ) {
        throw new Error(
          "expected assign('/'), got " + JSON.stringify(sandbox._assignTargets)
        );
      }
    }
  },
  {
    name: "login with redirect '//evil.example'",
    setup: function (sandbox) {
      var submitBtn = makeElement("nexus-submit", { disabled: false });
      var form = makeElement("nexus-login-form", {
        action: "/auth/login",
        querySelector: function () {
          return submitBtn;
        }
      });
      var tokenInput = makeElement("nexus-login-token", { value: "operator" });
      var errorEl = makeElement("nexus-login-error");

      sandbox._elements["nexus-login-form"] = form;
      sandbox._elements["nexus-login-token"] = tokenInput;
      sandbox._elements["nexus-login-error"] = errorEl;
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return { session_key: "K1", redirect: "//evil.example" };
        }
      });
    },
    run: async function (sandbox) {
      var form = sandbox.document.getElementById("nexus-login-form");
      form.getHandler("submit")({ preventDefault: function () {} });
      await tick();
      if (
        sandbox._assignTargets.length !== 1 ||
        sandbox._assignTargets[0] !== "/"
      ) {
        throw new Error(
          "expected assign('/'), got " + JSON.stringify(sandbox._assignTargets)
        );
      }
    }
  },
  {
    name: "login 401",
    setup: function (sandbox) {
      var submitBtn = makeElement("nexus-submit", { disabled: false });
      var form = makeElement("nexus-login-form", {
        action: "/auth/login",
        querySelector: function () {
          return submitBtn;
        }
      });
      var tokenInput = makeElement("nexus-login-token", { value: "operator" });
      var errorEl = makeElement("nexus-login-error");

      sandbox._elements["nexus-login-form"] = form;
      sandbox._elements["nexus-login-token"] = tokenInput;
      sandbox._elements["nexus-login-error"] = errorEl;
      sandbox._setResponse({
        status: 401,
        json: async function () {
          return {};
        }
      });
    },
    run: async function (sandbox) {
      var form = sandbox.document.getElementById("nexus-login-form");
      form.getHandler("submit")({ preventDefault: function () {} });
      await tick();
      var errorEl = sandbox.document.getElementById("nexus-login-error");
      if (errorEl.textContent !== "Invalid token.") {
        throw new Error(
          "expected error 'Invalid token.', got " +
            JSON.stringify(errorEl.textContent)
        );
      }
      if (sandbox._assignTargets.length !== 0) {
        throw new Error(
          "expected no assign, got " + JSON.stringify(sandbox._assignTargets)
        );
      }
    }
  },
  {
    name: "wrapped fetch adds session key to POST",
    setup: function (sandbox) {
      sandbox.localStorage.setItem(STORAGE_KEY, "K1");
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {};
        }
      });
    },
    run: async function (sandbox) {
      await sandbox.fetch("/diagnostics/cycle/freeze", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      var call = sandbox._fetchCalls[sandbox._fetchCalls.length - 1];
      if (!call) {
        throw new Error("fetch was not recorded");
      }
      var headers = call.init.headers;
      if (typeof headers.get !== "function") {
        throw new Error("recorded headers is not a Headers instance");
      }
      if (headers.get("x-nexus-session-key") !== "K1") {
        throw new Error(
          "missing X-Nexus-Session-Key, got " +
            headers.get("x-nexus-session-key")
        );
      }
      if (headers.get("content-type") !== "application/json") {
        throw new Error(
          "content-type not preserved, got " + headers.get("content-type")
        );
      }
    }
  },
  {
    name: "wrapped fetch GET does not add key",
    setup: function (sandbox) {
      sandbox.localStorage.setItem(STORAGE_KEY, "K1");
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {};
        }
      });
    },
    run: async function (sandbox) {
      await sandbox.fetch("/diagnostics/metrics.json", { method: "GET" });
      var call = sandbox._fetchCalls[sandbox._fetchCalls.length - 1];
      var headers = call.init && call.init.headers;
      if (headers && headers.get("x-nexus-session-key")) {
        throw new Error(
          "unexpected key header on GET: " +
            headers.get("x-nexus-session-key")
        );
      }
    }
  },
  {
    name: "wrapped fetch cross-origin does not add key",
    setup: function (sandbox) {
      sandbox.localStorage.setItem(STORAGE_KEY, "K1");
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {};
        }
      });
    },
    run: async function (sandbox) {
      await sandbox.fetch("https://other.example/x", { method: "POST" });
      var call = sandbox._fetchCalls[sandbox._fetchCalls.length - 1];
      var headers = call.init && call.init.headers;
      if (headers && headers.get("x-nexus-session-key")) {
        throw new Error(
          "unexpected key header for cross-origin: " +
            headers.get("x-nexus-session-key")
        );
      }
    }
  },
  {
    name: "wrapped fetch 401 redirects to login except on /auth",
    setup: function (sandbox) {
      sandbox.localStorage.setItem(STORAGE_KEY, "K1");
    },
    run: async function (sandbox) {
      sandbox._setResponse({
        status: 401,
        json: async function () {
          return {};
        }
      });
      await sandbox.fetch("/diagnostics/forks", { method: "GET" });
      if (sandbox.localStorage.getItem(STORAGE_KEY) !== null) {
        throw new Error("session key should be cleared after 401");
      }
      if (
        sandbox._assignTargets.length !== 1 ||
        sandbox._assignTargets[0] !== "/login"
      ) {
        throw new Error(
          "expected assign('/login'), got " +
            JSON.stringify(sandbox._assignTargets)
        );
      }

      sandbox.localStorage.setItem(STORAGE_KEY, "K2");
      sandbox._setResponse({
        status: 401,
        json: async function () {
          return {};
        }
      });
      await sandbox.fetch("/auth/login", { method: "POST" });
      if (sandbox.localStorage.getItem(STORAGE_KEY) !== "K2") {
        throw new Error("session key should not be cleared for /auth/ 401");
      }
      if (sandbox._assignTargets.length !== 1) {
        throw new Error(
          "expected no extra assign for /auth/login 401, got " +
            JSON.stringify(sandbox._assignTargets)
        );
      }
    }
  },
  {
    name: "logout button click",
    setup: function (sandbox) {
      sandbox.localStorage.setItem(STORAGE_KEY, "K1");
      var logoutBtn = makeElement("nexus-logout");
      sandbox._elements["nexus-logout"] = logoutBtn;
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {};
        }
      });
    },
    run: async function (sandbox) {
      var btn = sandbox.document.getElementById("nexus-logout");
      var handler = btn.getHandler("click");
      if (!handler) {
        throw new Error("logout click handler not attached");
      }
      handler();
      await tick();
      var logoutCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === "/auth/logout";
      });
      if (logoutCalls.length !== 1) {
        throw new Error(
          "expected one /auth/logout fetch, got " + logoutCalls.length
        );
      }
      if (
        !logoutCalls[0].init.method ||
        logoutCalls[0].init.method.toUpperCase() !== "POST"
      ) {
        throw new Error(
          "expected POST /auth/logout, got " + logoutCalls[0].init.method
        );
      }
      if (sandbox.localStorage.getItem(STORAGE_KEY) !== null) {
        throw new Error("session key should be cleared after logout");
      }
      if (
        sandbox._assignTargets.length !== 1 ||
        sandbox._assignTargets[0] !== "/login"
      ) {
        throw new Error(
          "expected assign('/login') after logout, got " +
            JSON.stringify(sandbox._assignTargets)
        );
      }
    }
  },
  {
    name: "EventSource wrapper probes on CLOSED error and throttles",
    setup: function (sandbox) {
      var FakeES = makeFakeEventSource();
      sandbox.EventSource = FakeES;
      sandbox.window.EventSource = FakeES;
      sandbox._fakeEventSourceClass = FakeES;
      sandbox._now = 0;
      sandbox.__nexusAuthNow = function () {
        return sandbox._now;
      };
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {};
        }
      });
    },
    run: async function (sandbox) {
      var FakeES = sandbox._fakeEventSourceClass;
      var Wrapped = sandbox.window.EventSource;
      if (!Wrapped) {
        throw new Error("EventSource wrapper was not installed");
      }
      if (
        Wrapped.CONNECTING !== FakeES.CONNECTING ||
        Wrapped.OPEN !== FakeES.OPEN ||
        Wrapped.CLOSED !== FakeES.CLOSED
      ) {
        throw new Error("wrapper is missing EventSource readyState constants");
      }

      var es = new Wrapped("/diagnostics/stream");
      if (FakeES.instances.length !== 1) {
        throw new Error(
          "expected one underlying EventSource instance, got " +
            FakeES.instances.length
        );
      }

      es.readyState = FakeES.CLOSED;
      es.triggerError();
      await tick();
      var probeCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === "/diagnostics/perception.json";
      });
      if (probeCalls.length !== 1) {
        throw new Error(
          "expected one probe after CLOSED error, got " + probeCalls.length
        );
      }
      if (probeCalls[0].init.cache !== "no-store") {
        throw new Error(
          "probe fetch should use cache: 'no-store', got " +
            probeCalls[0].init.cache
        );
      }

      es.readyState = FakeES.CLOSED;
      es.triggerError();
      await tick();
      probeCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === "/diagnostics/perception.json";
      });
      if (probeCalls.length !== 1) {
        throw new Error(
          "expected no second probe within 30 s, got " + probeCalls.length
        );
      }

      sandbox._now += 30000;
      es.readyState = FakeES.CLOSED;
      es.triggerError();
      await tick();
      probeCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === "/diagnostics/perception.json";
      });
      if (probeCalls.length !== 2) {
        throw new Error(
          "expected second probe after 30 s, got " + probeCalls.length
        );
      }
    }
  }
];

async function main() {
  var results = [];
  var allOk = true;
  for (var i = 0; i < scenarios.length; i++) {
    var scenario = scenarios[i];
    var sandbox = makeSandbox(scenario);
    runScript(sandbox);
    try {
      await scenario.run(sandbox);
      results.push({ name: scenario.name, ok: true });
    } catch (err) {
      allOk = false;
      results.push({ name: scenario.name, ok: false, error: err.message });
    }
  }
  var output = { ok: allOk, results: results };
  process.stdout.write(JSON.stringify(output) + "\n");
  process.exit(allOk ? 0 : 1);
}

main().catch(function (err) {
  process.stdout.write(
    JSON.stringify({ ok: false, error: err.message, results: [] }) + "\n"
  );
  process.exit(1);
});
