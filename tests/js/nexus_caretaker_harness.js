const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(ROOT, "kaine", "nexus", "static", "nexus_caretaker.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

const START_ID = "abcdef0123456789abcdef0123456789";

function makeElement(id, extras) {
  extras = extras || {};
  var handlers = {};
  var dataset = {};
  var el = {
    id: id,
    textContent: "",
    hidden: true,
    disabled: false,
    dataset: dataset,
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

function makeSandbox(scenario) {
  var fetchCalls = [];
  var nextResponse = {
    status: 200,
    json: async function () { return {}; }
  };

  var elements = {};

  var document = {
    readyState: "complete",
    addEventListener: function () {},
    getElementById: function (id) {
      return elements[id] || null;
    }
  };

  function fakeFetch(url, init) {
    fetchCalls.push({ url: url, init: init || {} });
    var resp = nextResponse;
    if (typeof resp === "function") {
      resp = resp(url, init || {});
    }
    // Like a real Response, `ok` follows the status unless a scenario sets it.
    if (resp && resp.ok === undefined && typeof resp.status === "number") {
      resp = Object.assign({ ok: resp.status >= 200 && resp.status < 300 }, resp);
    }
    return Promise.resolve(resp);
  }

  var sandbox = {
    window: undefined,
    document: document,
    fetch: fakeFetch,
    Headers: globalThis.Headers,
    Request: globalThis.Request,
    URL: globalThis.URL,
    Promise: globalThis.Promise,
    Date: globalThis.Date,
    JSON: globalThis.JSON,
    console: globalThis.console,
    setInterval: function () {},
    clearInterval: function () {},
    _elements: elements,
    _fetchCalls: fetchCalls,
    _setResponse: function (resp) {
      nextResponse = resp;
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
  vm.runInNewContext(source, sandbox, { filename: "nexus_caretaker.js" });
}

function requireNoInnerHTML() {
  if (source.indexOf("innerHTML") !== -1) {
    throw new Error("source uses innerHTML");
  }
}

var scenarios = [
  {
    name: "pending response shows banner and sets dataset.startId",
    setup: function (sandbox) {
      var banner = makeElement("caretaker-banner");
      var since = makeElement("caretaker-banner-since");
      var ackBtn = makeElement("caretaker-ack", { hidden: false });
      var msg = makeElement("caretaker-ack-msg");
      sandbox._elements["caretaker-banner"] = banner;
      sandbox._elements["caretaker-banner-since"] = since;
      sandbox._elements["caretaker-ack"] = ackBtn;
      sandbox._elements["caretaker-ack-msg"] = msg;
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: true,
            start_id: START_ID,
            started_at: "2026-01-01T00:00:00+00:00",
            acknowledged_at: null
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var banner = sandbox.document.getElementById("caretaker-banner");
      var since = sandbox.document.getElementById("caretaker-banner-since");
      var ackBtn = sandbox.document.getElementById("caretaker-ack");
      if (banner.hidden) {
        throw new Error("banner should be visible for pending start");
      }
      if (since.textContent !== " since 2026-01-01T00:00:00+00:00") {
        throw new Error("unexpected since text: " + JSON.stringify(since.textContent));
      }
      if (ackBtn.dataset.startId !== START_ID) {
        throw new Error("expected startId " + START_ID + ", got " + ackBtn.dataset.startId);
      }
    }
  },
  {
    name: "not-pending response hides banner",
    setup: function (sandbox) {
      var banner = makeElement("caretaker-banner", { hidden: false });
      var since = makeElement("caretaker-banner-since", { textContent: " leftover " });
      var ackBtn = makeElement("caretaker-ack", { dataset: { startId: START_ID } });
      var msg = makeElement("caretaker-ack-msg");
      sandbox._elements["caretaker-banner"] = banner;
      sandbox._elements["caretaker-banner-since"] = since;
      sandbox._elements["caretaker-ack"] = ackBtn;
      sandbox._elements["caretaker-ack-msg"] = msg;
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            start_id: null,
            started_at: null,
            acknowledged_at: null
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var banner = sandbox.document.getElementById("caretaker-banner");
      var since = sandbox.document.getElementById("caretaker-banner-since");
      var ackBtn = sandbox.document.getElementById("caretaker-ack");
      if (!banner.hidden) {
        throw new Error("banner should be hidden when not pending");
      }
      if (since.textContent !== "") {
        throw new Error("since text should be cleared, got " + JSON.stringify(since.textContent));
      }
      if (ackBtn.dataset.startId !== "") {
        throw new Error("startId should be cleared, got " + ackBtn.dataset.startId);
      }
    }
  },
  {
    name: "clicking acknowledge POSTs start_id and refreshes status",
    setup: function (sandbox) {
      var banner = makeElement("caretaker-banner");
      var since = makeElement("caretaker-banner-since");
      var ackBtn = makeElement("caretaker-ack", { hidden: false });
      var msg = makeElement("caretaker-ack-msg");
      sandbox._elements["caretaker-banner"] = banner;
      sandbox._elements["caretaker-banner-since"] = since;
      sandbox._elements["caretaker-ack"] = ackBtn;
      sandbox._elements["caretaker-ack-msg"] = msg;
      sandbox._setResponse(function (url, init) {
        if (url === "/diagnostics/caretaker.json") {
          return {
            status: 200,
            json: async function () {
              return {
                pending: true,
                start_id: START_ID,
                started_at: "2026-01-01T00:00:00+00:00",
                acknowledged_at: null
              };
            }
          };
        }
        if (url === "/diagnostics/caretaker/ack") {
          return {
            status: 200,
            json: async function () {
              return {
                pending: false,
                start_id: START_ID,
                started_at: "2026-01-01T00:00:00+00:00",
                acknowledged_at: "2026-01-01T00:00:01+00:00"
              };
            }
          };
        }
        return { status: 404, json: async function () { return {}; } };
      });
    },
    run: async function (sandbox) {
      await tick();
      var ackBtn = sandbox.document.getElementById("caretaker-ack");
      var handler = ackBtn.getHandler("click");
      if (!handler) {
        throw new Error("click handler not attached");
      }
      handler();
      await tick();

      var postCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === "/diagnostics/caretaker/ack" &&
               call.init.method &&
               call.init.method.toUpperCase() === "POST";
      });
      if (postCalls.length !== 1) {
        throw new Error("expected one POST ack, got " + postCalls.length);
      }
      var body = JSON.parse(postCalls[0].init.body);
      if (body.start_id !== START_ID) {
        throw new Error("expected body start_id " + START_ID + ", got " + body.start_id);
      }
      var headers = postCalls[0].init.headers;
      var contentType = "";
      if (headers && typeof headers.get === "function") {
        contentType = headers.get("content-type") || "";
      } else if (headers && headers["Content-Type"]) {
        contentType = headers["Content-Type"];
      }
      if (contentType !== "application/json") {
        throw new Error("expected content-type application/json, got " + contentType);
      }

      var getCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === "/diagnostics/caretaker.json" &&
               (!call.init.method || call.init.method.toUpperCase() === "GET");
      });
      if (getCalls.length < 2) {
        throw new Error("expected at least two status fetches, got " + getCalls.length);
      }

      var msg = sandbox.document.getElementById("caretaker-ack-msg");
      if (msg.textContent !== "acknowledged") {
        throw new Error("expected 'acknowledged', got " + JSON.stringify(msg.textContent));
      }
      if (ackBtn.disabled) {
        throw new Error("button should be re-enabled after request");
      }
    }
  },
  {
    name: "failed ack POST shows failed and re-enables button",
    setup: function (sandbox) {
      var banner = makeElement("caretaker-banner");
      var since = makeElement("caretaker-banner-since");
      var ackBtn = makeElement("caretaker-ack", {
        hidden: false,
        dataset: { startId: START_ID }
      });
      var msg = makeElement("caretaker-ack-msg");
      sandbox._elements["caretaker-banner"] = banner;
      sandbox._elements["caretaker-banner-since"] = since;
      sandbox._elements["caretaker-ack"] = ackBtn;
      sandbox._elements["caretaker-ack-msg"] = msg;
      sandbox._setResponse(function (url, init) {
        if (url === "/diagnostics/caretaker.json") {
          return {
            status: 200,
            json: async function () {
              return {
                pending: true,
                start_id: START_ID,
                started_at: "2026-01-01T00:00:00+00:00",
                acknowledged_at: null
              };
            }
          };
        }
        return { status: 500, json: async function () { return { detail: "ouch" }; } };
      });
    },
    run: async function (sandbox) {
      await tick();
      var ackBtn = sandbox.document.getElementById("caretaker-ack");
      ackBtn.getHandler("click")();
      await tick();
      var msg = sandbox.document.getElementById("caretaker-ack-msg");
      if (msg.textContent !== "failed") {
        throw new Error("expected 'failed', got " + JSON.stringify(msg.textContent));
      }
      if (ackBtn.disabled) {
        throw new Error("button should be re-enabled after failed request");
      }
    }
  },
  {
    name: "uses NexusVisibility.pausable when available",
    setup: function (sandbox) {
      var calls = [];
      sandbox.window.NexusVisibility = {
        pausable: function (fn, ms) { calls.push({ fn: fn, ms: ms }); }
      };
      sandbox._visibilityCalls = calls;
      sandbox._setResponse({
        status: 200,
        json: async function () { return {}; }
      });
    },
    run: async function (sandbox) {
      await tick();
      if (sandbox._visibilityCalls.length !== 1) {
        throw new Error("expected one pausable call, got " + sandbox._visibilityCalls.length);
      }
      if (sandbox._visibilityCalls[0].ms !== 15000) {
        throw new Error("expected interval 15000, got " + sandbox._visibilityCalls[0].ms);
      }
    }
  }
];

async function main() {
  var results = [];
  var allOk = true;

  try {
    requireNoInnerHTML();
    results.push({ name: "no innerHTML use", ok: true });
  } catch (err) {
    allOk = false;
    results.push({ name: "no innerHTML use", ok: false, error: err.message });
  }

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

  process.stdout.write(JSON.stringify({ ok: allOk, results: results }) + "\n");
  process.exit(allOk ? 0 : 1);
}

main().catch(function (err) {
  process.stdout.write(
    JSON.stringify({ ok: false, error: err.message, results: [] }) + "\n"
  );
  process.exit(1);
});
