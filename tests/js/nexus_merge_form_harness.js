const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(ROOT, "kaine", "nexus", "static", "nexus.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

function makeElement(id, extras) {
  extras = extras || {};
  var handlers = {};
  var _textContent = extras.textContent || "";
  var _value = extras.value !== undefined ? extras.value : "";
  var _color = "";
  var style = {
    get color() { return _color; },
    set color(v) { _color = v; }
  };
  var dataset = extras.dataset || {};
  var el = {
    id: id,
    dataset: dataset,
    hidden: !!extras.hidden,
    disabled: !!extras.disabled,
    get textContent() { return _textContent; },
    set textContent(v) { _textContent = v; },
    get value() { return _value; },
    set value(v) { _value = v; },
    style: style,
    addEventListener: function (type, fn) { handlers[type] = fn; },
    getHandler: function (type) { return handlers[type]; },
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
      // Language builtins (Array, Object, Number, ...) come from the real
      // global; only browser APIs the stub does not model become no-ops.
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
  vm.runInNewContext(source, sandbox, { filename: "nexus.js" });
}

var scenarios = [
  {
    name: "merge with world model from B sends choice and resets select",
    worldModel: "b",
    response: {
      status: 200,
      json: async function () { return { id: "m1", parent_id: "aaaa", label: "" }; }
    },
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["merge-form"] = makeElement("merge-form");
      els["merge-a"] = makeElement("merge-a", { value: "aaaa" });
      els["merge-b"] = makeElement("merge-b", { value: "bbbb" });
      els["merge-label"] = makeElement("merge-label", { value: "" });
      els["merge-world-model"] = makeElement("merge-world-model", { value: this.worldModel });
      els["merge-status"] = makeElement("merge-status");
      sandbox._setResponse(this.response);
    },
    run: function (sandbox) {
      var calls = sandbox._fetchCalls;
      if (calls.length !== 1) throw new Error("expected 1 fetch, got " + calls.length);
      var call = calls[0];
      if (call.url !== "/diagnostics/merges") throw new Error("unexpected url: " + call.url);
      var body = JSON.parse(call.init.body);
      if (body.snapshot_a_id !== "aaaa" || body.snapshot_b_id !== "bbbb") {
        throw new Error("unexpected snapshot ids: " + JSON.stringify(body));
      }
      if (body.world_model_from !== "b") {
        throw new Error("expected world_model_from === 'b', got " + body.world_model_from);
      }
      var select = sandbox.document.getElementById("merge-world-model");
      if (select.value !== "") {
        throw new Error("select value should reset to '', got " + select.value);
      }
    }
  },
  {
    name: "merge without world model omits key from body",
    worldModel: "",
    response: {
      status: 200,
      json: async function () { return { id: "m2", parent_id: "aaaa", label: "" }; }
    },
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["merge-form"] = makeElement("merge-form");
      els["merge-a"] = makeElement("merge-a", { value: "aaaa" });
      els["merge-b"] = makeElement("merge-b", { value: "bbbb" });
      els["merge-label"] = makeElement("merge-label", { value: "" });
      els["merge-world-model"] = makeElement("merge-world-model", { value: this.worldModel });
      els["merge-status"] = makeElement("merge-status");
      sandbox._setResponse(this.response);
    },
    run: function (sandbox) {
      var calls = sandbox._fetchCalls;
      if (calls.length !== 1) throw new Error("expected 1 fetch, got " + calls.length);
      var body = JSON.parse(calls[0].init.body);
      if ("world_model_from" in body) {
        throw new Error("body should not contain world_model_from: " + JSON.stringify(body));
      }
    }
  },
  {
    name: "409 string detail is rendered in status",
    worldModel: "",
    response: {
      status: 409,
      json: async function () { return { detail: "both parents carry a Phantasia world model; choose" }; }
    },
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["merge-form"] = makeElement("merge-form");
      els["merge-a"] = makeElement("merge-a", { value: "aaaa" });
      els["merge-b"] = makeElement("merge-b", { value: "bbbb" });
      els["merge-label"] = makeElement("merge-label", { value: "" });
      els["merge-world-model"] = makeElement("merge-world-model", { value: this.worldModel });
      els["merge-status"] = makeElement("merge-status");
      sandbox._setResponse(this.response);
    },
    run: function (sandbox) {
      var status = sandbox.document.getElementById("merge-status");
      var text = status.textContent;
      if (text.indexOf("409") === -1) throw new Error("expected 409 in status, got " + JSON.stringify(text));
      if (text.indexOf("both parents carry a Phantasia world model; choose") === -1) {
        throw new Error("expected detail in status, got " + JSON.stringify(text));
      }
    }
  },
  {
    name: "422 array detail joins msg values",
    worldModel: "",
    response: {
      status: 422,
      json: async function () {
        return {
          detail: [{ loc: ["body", "world_model_from"], msg: "Input should be 'a' or 'b'" }]
        };
      }
    },
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["merge-form"] = makeElement("merge-form");
      els["merge-a"] = makeElement("merge-a", { value: "aaaa" });
      els["merge-b"] = makeElement("merge-b", { value: "bbbb" });
      els["merge-label"] = makeElement("merge-label", { value: "" });
      els["merge-world-model"] = makeElement("merge-world-model", { value: this.worldModel });
      els["merge-status"] = makeElement("merge-status");
      sandbox._setResponse(this.response);
    },
    run: function (sandbox) {
      var status = sandbox.document.getElementById("merge-status");
      var text = status.textContent;
      if (text.indexOf("422") === -1) throw new Error("expected 422 in status, got " + JSON.stringify(text));
      if (text.indexOf("Input should be 'a' or 'b'") === -1) {
        throw new Error("expected validation msg in status, got " + JSON.stringify(text));
      }
    }
  },
  {
    name: "500 null detail renders bare status",
    worldModel: "",
    response: {
      status: 500,
      json: async function () { return null; }
    },
    setup: function (sandbox) {
      var els = sandbox._elements;
      els["merge-form"] = makeElement("merge-form");
      els["merge-a"] = makeElement("merge-a", { value: "aaaa" });
      els["merge-b"] = makeElement("merge-b", { value: "bbbb" });
      els["merge-label"] = makeElement("merge-label", { value: "" });
      els["merge-world-model"] = makeElement("merge-world-model", { value: this.worldModel });
      els["merge-status"] = makeElement("merge-status");
      sandbox._setResponse(this.response);
    },
    run: function (sandbox) {
      var status = sandbox.document.getElementById("merge-status");
      if (status.textContent !== "failed: 500") {
        throw new Error("expected 'failed: 500', got " + JSON.stringify(status.textContent));
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
      sandbox.NexusControls.attach();
    } catch (err) {
      allOk = false;
      failures.push({ name: scenario.name + " (attach)", error: err.message });
      continue;
    }

    var form = sandbox.document.getElementById("merge-form");
    var handler = form && form.getHandler("submit");
    if (!handler) {
      allOk = false;
      failures.push({ name: scenario.name + " (handler)", error: "submit handler not registered" });
      continue;
    }

    try {
      await handler({ preventDefault: function () {} });
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
