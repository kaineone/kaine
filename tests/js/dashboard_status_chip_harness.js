const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(ROOT, "kaine", "dashboard", "static", "dashboard.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

function makeElement(id, extras) {
  extras = extras || {};
  var handlers = {};
  var _textContent = extras.textContent || "";
  var _value = extras.value !== undefined ? extras.value : "";
  var _color = "";
  var _className = extras.className || "";
  var attrs = {};
  var classes = {};
  var dataset = extras.dataset || {};
  var style = {
    get color() { return _color; },
    set color(v) { _color = v; }
  };
  var el = {
    id: id,
    dataset: dataset,
    hidden: !!extras.hidden,
    disabled: !!extras.disabled,
    get className() { return _className; },
    set className(v) { _className = v; },
    get textContent() { return _textContent; },
    set textContent(v) { _textContent = v; },
    get value() { return _value; },
    set value(v) { _value = v; },
    style: style,
    classList: {
      toggle: function (cls, force) {
        if (force === undefined) force = !classes[cls];
        classes[cls] = !!force;
      },
      contains: function (cls) { return !!classes[cls]; },
      _classes: classes
    },
    addEventListener: function (type, fn) { handlers[type] = fn; },
    getHandler: function (type) { return handlers[type]; },
    setAttribute: function (name, value) { attrs[name] = String(value); },
    getAttribute: function (name) { return name in attrs ? attrs[name] : null; },
    removeAttribute: function (name) { delete attrs[name]; },
    hasAttribute: function (name) { return name in attrs; },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    closest: function () { return null; },
    remove: function () {}
  };
  return new Proxy(el, {
    get: function (target, prop) {
      if (prop in target) return target[prop];
      if (typeof prop === "symbol") return undefined;
      return function () { return null; };
    }
  });
}

function makeDocument(elements) {
  var doc = {
    readyState: "complete",
    addEventListener: function () {},
    getElementById: function (id) { return elements[id] || null; },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    createElement: function () { return makeElement(null); },
    body: null
  };
  return new Proxy(doc, {
    get: function (target, prop) {
      if (prop in target) return target[prop];
      if (typeof prop === "symbol") return undefined;
      return function () { return null; };
    }
  });
}

function makeResponse(status, body) {
  return {
    status: status,
    ok: status >= 200 && status < 300,
    json: function () { return Promise.resolve(body); }
  };
}

function metricsAndHealthResponse(metricsBody, healthBody) {
  return function (url) {
    if (url.indexOf("/diagnostics/metrics.json") !== -1) {
      return makeResponse(200, metricsBody);
    }
    if (url.indexOf("/diagnostics/health.json") !== -1) {
      return makeResponse(200, healthBody);
    }
    return makeResponse(200, {});
  };
}

function makeSandbox(scenario) {
  var elements = {};
  var document = makeDocument(elements);
  var fetchCalls = [];
  var nextResponse = { status: 200, json: async function () { return {}; } };

  function fakeFetch(url, init) {
    fetchCalls.push({ url: url, init: init || {} });
    var resp = nextResponse;
    if (typeof resp === "function") resp = resp(url, init || {});
    if (resp && resp.ok === undefined && typeof resp.status === "number") {
      resp = Object.assign({ ok: resp.status >= 200 && resp.status < 300 }, resp);
    }
    return Promise.resolve(resp);
  }

  var target = {
    window: undefined,
    document: document,
    fetch: fakeFetch,
    confirm: function () { return true; },
    sessionStorage: { getItem: function () {}, setItem: function () {}, removeItem: function () {} },
    localStorage: { getItem: function () {}, setItem: function () {}, removeItem: function () {} },
    matchMedia: function () {
      return {
        matches: false,
        media: "",
        addListener: function () {},
        removeListener: function () {},
        addEventListener: function () {},
        removeEventListener: function () {}
      };
    },
    EventSource: function () { this.close = function () {}; },
    navigator: { userAgent: "node", onLine: true, language: "en" },
    location: {
      href: "http://test/diagnostics/",
      pathname: "/diagnostics/",
      search: "",
      hash: "",
      host: "test",
      protocol: "http:"
    },
    Headers: globalThis.Headers,
    Request: globalThis.Request,
    Response: globalThis.Response,
    URL: globalThis.URL,
    Promise: globalThis.Promise,
    Date: globalThis.Date,
    JSON: globalThis.JSON,
    console: globalThis.console,
    setInterval: function () {},
    clearInterval: function () {},
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    requestAnimationFrame: function () {},
    cancelAnimationFrame: function () {},
    MutationObserver: function () { this.observe = function () {}; this.disconnect = function () {}; },
    ResizeObserver: function () { this.observe = function () {}; this.disconnect = function () {}; },
    _elements: elements,
    _fetchCalls: fetchCalls,
    _setResponse: function (resp) { nextResponse = resp; }
  };

  var sandbox = new Proxy(target, {
    get: function (tgt, prop) {
      if (prop in tgt) return tgt[prop];
      if (typeof prop === "symbol") return undefined;
      if (prop in globalThis) return globalThis[prop];
      return function () { return null; };
    }
  });

  sandbox.window = sandbox;

  if (scenario && scenario.setup) {
    scenario.setup(sandbox);
  }

  return sandbox;
}

function runScript(sandbox) {
  vm.runInNewContext(source, sandbox, { filename: "dashboard.js" });
}

function installStreamStub(sandbox) {
  var subscribers = [];
  sandbox.window.DashboardStream = {
    init: function () {},
    subscribe: function (fn) { subscribers.push(fn); return function () {}; },
    onStatus: function (fn) { return function () {}; }
  };
  sandbox._streamSubscribers = subscribers;
}

function sleep(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

var HEALTH_BODY = {
  cycle_pacing: {
    state: "nominal",
    time_scale: 1,
    target_rate_hz: 1,
    achieved_rate_hz: 1,
    mean_tick_ms: 1,
    mean_slip_ms: 0,
    max_slip_ms: 0,
    overrunning: false,
    overrun_ticks: 0,
    window_ticks: 1
  },
  modules: []
};

var scenarios = [
  {
    name: "sleeping=true with running metrics shows sleeping",
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["sleep-badge"] = makeElement("sleep-badge", { dataset: { sleeping: "true" }, textContent: "offline" });
      els["cycle-not-running"] = makeElement("cycle-not-running");
      els["cycle-charts"] = makeElement("cycle-charts");
      els["metrics"] = makeElement("metrics");
      sandbox._setResponse(metricsAndHealthResponse(
        { cycle_status: "running", frozen: false, run_id: "r1" },
        HEALTH_BODY
      ));
    },
    run: async function (sandbox) {
      await sleep(0);
      await sleep(0);
      var badge = sandbox.document.getElementById("sleep-badge");
      if (badge.textContent !== "sleeping") {
        throw new Error("expected sleeping, got " + JSON.stringify(badge.textContent));
      }
    }
  },
  {
    name: "sleeping=false with running metrics shows awake",
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["sleep-badge"] = makeElement("sleep-badge", { dataset: { sleeping: "false" }, textContent: "offline" });
      els["cycle-not-running"] = makeElement("cycle-not-running");
      els["cycle-charts"] = makeElement("cycle-charts");
      els["metrics"] = makeElement("metrics");
      sandbox._setResponse(metricsAndHealthResponse(
        { cycle_status: "running", frozen: false, run_id: "r1" },
        HEALTH_BODY
      ));
    },
    run: async function (sandbox) {
      await sleep(0);
      await sleep(0);
      var badge = sandbox.document.getElementById("sleep-badge");
      if (badge.textContent !== "awake") {
        throw new Error("expected awake, got " + JSON.stringify(badge.textContent));
      }
    }
  },
  {
    name: "sleeping=true with not-running metrics shows offline",
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["sleep-badge"] = makeElement("sleep-badge", { dataset: { sleeping: "true" }, textContent: "offline" });
      els["cycle-not-running"] = makeElement("cycle-not-running");
      els["cycle-charts"] = makeElement("cycle-charts");
      els["metrics"] = makeElement("metrics");
      sandbox._setResponse(metricsAndHealthResponse(
        { cycle_status: "not running", frozen: false, run_id: "r1" },
        HEALTH_BODY
      ));
    },
    run: async function (sandbox) {
      await sleep(0);
      await sleep(0);
      var badge = sandbox.document.getElementById("sleep-badge");
      if (badge.textContent !== "offline") {
        throw new Error("expected offline, got " + JSON.stringify(badge.textContent));
      }
    }
  },
  {
    name: "sleep completed stream event flips sleeping badge to awake",
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["sleep-badge"] = makeElement("sleep-badge", { dataset: { sleeping: "true" }, textContent: "offline" });
      els["cycle-not-running"] = makeElement("cycle-not-running");
      els["cycle-charts"] = makeElement("cycle-charts");
      els["metrics"] = makeElement("metrics");
      sandbox._setResponse(metricsAndHealthResponse(
        { cycle_status: "running", frozen: false, run_id: "r1" },
        HEALTH_BODY
      ));
    },
    run: async function (sandbox) {
      await sleep(0);
      await sleep(0);
      var badge = sandbox.document.getElementById("sleep-badge");
      if (badge.textContent !== "sleeping") {
        throw new Error("expected sleeping before wake event, got " + JSON.stringify(badge.textContent));
      }
      sandbox._streamSubscribers.forEach(function (fn) {
        fn({ source: "sleep", type: "sleep.sleep.completed", payload: {} });
      });
      await sleep(0);
      if (badge.textContent !== "awake") {
        throw new Error("expected awake after wake event, got " + JSON.stringify(badge.textContent));
      }
    }
  }
];

async function main() {
  var failures = [];
  var allOk = true;

  for (var i = 0; i < scenarios.length; i++) {
    var scenario = scenarios[i];
    var sandbox = makeSandbox(scenario);

    try {
      runScript(sandbox);
    } catch (err) {
      allOk = false;
      failures.push({ name: scenario.name + " (load)", error: err.message });
      continue;
    }

    try {
      installStreamStub(sandbox);
    } catch (err) {
      allOk = false;
      failures.push({ name: scenario.name + " (stub)", error: err.message });
      continue;
    }

    try {
      sandbox.window.DashboardVitals.init();
    } catch (err) {
      allOk = false;
      failures.push({ name: scenario.name + " (init)", error: err.message });
      continue;
    }

    try {
      await scenario.run(sandbox);
    } catch (err) {
      allOk = false;
      failures.push({ name: scenario.name, error: err.message });
    }
  }

  process.stdout.write(JSON.stringify({ ok: allOk, failures: failures }) + "\n");
  process.exit(allOk ? 0 : 1);
}

main().catch(function (err) {
  process.stdout.write(JSON.stringify({ ok: false, failures: [{ name: "main", error: err.message }] }) + "\n");
  process.exit(1);
});
