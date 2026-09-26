const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(ROOT, "kaine", "nexus", "static", "nexus_birth.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

const REQUEST_ID = "abcdef0123456789abcdef0123456789";

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

function makeElement(tag, attrs) {
  attrs = attrs || {};
  var handlers = {};
  var dataset = {};
  var el = {
    tagName: tag,
    id: attrs.id || "",
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
  delete attrs.id;
  for (var key in attrs) {
    if (Object.prototype.hasOwnProperty.call(attrs, key)) {
      el[key] = attrs[key];
    }
  }
  return el;
}

function makePanelElements(sandbox) {
  var elements = sandbox._elements;
  elements[PANEL_ID] = makeElement("section", { id: PANEL_ID });
  elements[STAGE_ID] = makeElement("div", { id: STAGE_ID });
  elements[LIVED_ID] = makeElement("span", { id: LIVED_ID });
  elements[SLEEPS_ID] = makeElement("span", { id: SLEEPS_ID });
  elements[PASSES_ID] = makeElement("span", { id: PASSES_ID });
  elements[READINESS_ID] = makeElement("div", { id: READINESS_ID });
  elements[DECISION_ID] = makeElement("div", { id: DECISION_ID });
  elements[ACK_ID] = makeElement("div", { id: ACK_ID });
  elements[ACK_START_ID] = makeElement("button", { id: ACK_START_ID, hidden: false });
  elements[ACK_CONFIRM_ROW_ID] = makeElement("div", { id: ACK_CONFIRM_ROW_ID });
  elements[ACK_CONFIRM_ID] = makeElement("button", { id: ACK_CONFIRM_ID, hidden: false });
  elements[ACK_CANCEL_ID] = makeElement("button", { id: ACK_CANCEL_ID, hidden: false });
  elements[ACK_MSG_ID] = makeElement("span", { id: ACK_MSG_ID });
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
    Array: globalThis.Array,
    Object: globalThis.Object,
    String: globalThis.String,
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
  vm.runInNewContext(source, sandbox, { filename: "nexus_birth.js" });
}

function requireNoInnerHTML() {
  if (source.indexOf("innerHTML") !== -1) {
    throw new Error("source uses innerHTML");
  }
}

var scenarios = [
  {
    name: "null development hides panel",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            request_id: null,
            development: null
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var panel = sandbox.document.getElementById(PANEL_ID);
      if (!panel.hidden) {
        throw new Error("panel should be hidden when development is null");
      }
    }
  },
  {
    name: "development renders stage and evidence",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            request_id: null,
            development: {
              stage: "gestation",
              gestation_started_at: "2026-01-01T00:00:00+00:00",
              born_at: null,
              lived_seconds: 7200,
              sleep_count: 3,
              consolidation_passes: 1,
              readiness: { ready: false, passed: [], unmet: [] },
              readout: {},
              decision: null,
              awaiting_ack: false
            }
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var panel = sandbox.document.getElementById(PANEL_ID);
      var stage = sandbox.document.getElementById(STAGE_ID);
      var lived = sandbox.document.getElementById(LIVED_ID);
      var sleeps = sandbox.document.getElementById(SLEEPS_ID);
      var passes = sandbox.document.getElementById(PASSES_ID);
      if (panel.hidden) {
        throw new Error("panel should be visible when development is present");
      }
      if (stage.textContent !== "gestation") {
        throw new Error("unexpected stage text: " + JSON.stringify(stage.textContent));
      }
      if (lived.textContent !== "2.0") {
        throw new Error("unexpected lived text: " + JSON.stringify(lived.textContent));
      }
      if (sleeps.textContent !== "3") {
        throw new Error("unexpected sleeps text: " + JSON.stringify(sleeps.textContent));
      }
      if (passes.textContent !== "1") {
        throw new Error("unexpected passes text: " + JSON.stringify(passes.textContent));
      }
    }
  },
  {
    name: "readiness renders passed and unmet markers with readout",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            request_id: null,
            development: {
              stage: "gestation",
              readiness: { ready: false, passed: ["a", "b"], unmet: ["c"] },
              readout: { a: 0.9, b: 5, c: 0 }
            }
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var readiness = sandbox.document.getElementById(READINESS_ID);
      var text = readiness.textContent;
      if (text.indexOf("✓ a (0.9)") === -1) {
        throw new Error("expected passed marker a with readout, got " + JSON.stringify(text));
      }
      if (text.indexOf("✓ b (5)") === -1) {
        throw new Error("expected passed marker b with readout, got " + JSON.stringify(text));
      }
      if (text.indexOf("✗ c (0)") === -1) {
        throw new Error("expected unmet marker c with readout, got " + JSON.stringify(text));
      }
    }
  },
  {
    name: "decision renders action and reason",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            request_id: null,
            development: {
              stage: "ready",
              decision: { action: "hold", reason: "not ready" }
            }
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var decision = sandbox.document.getElementById(DECISION_ID);
      if (decision.hidden) {
        throw new Error("decision block should be visible");
      }
      var text = decision.textContent;
      if (text.indexOf("action: hold") === -1) {
        throw new Error("expected decision action, got " + JSON.stringify(text));
      }
      if (text.indexOf("reason: not ready") === -1) {
        throw new Error("expected decision reason, got " + JSON.stringify(text));
      }
    }
  },
  {
    name: "ack block hidden when not pending",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            request_id: null,
            development: { stage: "gestation" }
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var ack = sandbox.document.getElementById(ACK_ID);
      if (!ack.hidden) {
        throw new Error("ack block should be hidden when not pending");
      }
    }
  },
  {
    name: "pending ack two-step posts request_id once and refreshes",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse(function (url, init) {
        if (url === STATUS_URL) {
          return {
            status: 200,
            json: async function () {
              return {
                pending: true,
                request_id: REQUEST_ID,
                development: { stage: "ready", awaiting_ack: true }
              };
            }
          };
        }
        if (url === ACK_URL) {
          return {
            status: 200,
            json: async function () {
              return {
                pending: false,
                request_id: REQUEST_ID,
                development: { stage: "born" }
              };
            }
          };
        }
        return { status: 404, json: async function () { return {}; } };
      });
    },
    run: async function (sandbox) {
      await tick();
      var ack = sandbox.document.getElementById(ACK_ID);
      var startBtn = sandbox.document.getElementById(ACK_START_ID);
      var confirmRow = sandbox.document.getElementById(ACK_CONFIRM_ROW_ID);
      var confirmBtn = sandbox.document.getElementById(ACK_CONFIRM_ID);
      var cancelBtn = sandbox.document.getElementById(ACK_CANCEL_ID);
      var msg = sandbox.document.getElementById(ACK_MSG_ID);

      if (ack.hidden) {
        throw new Error("ack block should be visible when pending");
      }
      if (confirmBtn.dataset.requestId !== REQUEST_ID) {
        throw new Error("expected requestId " + REQUEST_ID + ", got " + confirmBtn.dataset.requestId);
      }

      startBtn.getHandler("click")();
      await tick();
      if (!startBtn.hidden) {
        throw new Error("start button should be hidden after first click");
      }
      if (confirmRow.hidden) {
        throw new Error("confirm row should be visible after first click");
      }
      var postCallsBefore = sandbox._fetchCalls.filter(function (call) {
        return call.url === ACK_URL &&
               call.init.method &&
               call.init.method.toUpperCase() === "POST";
      }).length;
      if (postCallsBefore !== 0) {
        throw new Error("first click should not POST, got " + postCallsBefore);
      }

      cancelBtn.getHandler("click")();
      await tick();
      if (startBtn.hidden) {
        throw new Error("start button should be visible after cancel");
      }
      if (!confirmRow.hidden) {
        throw new Error("confirm row should be hidden after cancel");
      }

      startBtn.getHandler("click")();
      await tick();
      confirmBtn.getHandler("click")();
      await tick();

      var postCalls = sandbox._fetchCalls.filter(function (call) {
        return call.url === ACK_URL &&
               call.init.method &&
               call.init.method.toUpperCase() === "POST";
      });
      if (postCalls.length !== 1) {
        throw new Error("expected one POST ack, got " + postCalls.length);
      }
      var body = JSON.parse(postCalls[0].init.body);
      if (body.request_id !== REQUEST_ID) {
        throw new Error("expected body request_id " + REQUEST_ID + ", got " + body.request_id);
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
        return call.url === STATUS_URL &&
               (!call.init.method || call.init.method.toUpperCase() === "GET");
      });
      if (getCalls.length < 2) {
        throw new Error("expected at least two status fetches, got " + getCalls.length);
      }

      if (msg.textContent !== "birth acknowledged") {
        throw new Error("expected 'birth acknowledged', got " + JSON.stringify(msg.textContent));
      }
      if (confirmBtn.disabled) {
        throw new Error("confirm button should be re-enabled after request");
      }
    }
  },
  {
    name: "failed ack POST shows server detail and re-enables button",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse(function (url, init) {
        if (url === STATUS_URL) {
          return {
            status: 200,
            json: async function () {
              return {
                pending: true,
                request_id: REQUEST_ID,
                development: { stage: "ready" }
              };
            }
          };
        }
        return {
          status: 409,
          json: async function () {
            return { detail: "no birth awaiting acknowledgement" };
          }
        };
      });
    },
    run: async function (sandbox) {
      await tick();
      var startBtn = sandbox.document.getElementById(ACK_START_ID);
      var confirmBtn = sandbox.document.getElementById(ACK_CONFIRM_ID);
      var msg = sandbox.document.getElementById(ACK_MSG_ID);

      startBtn.getHandler("click")();
      await tick();
      confirmBtn.getHandler("click")();
      await tick();

      if (msg.textContent !== "failed: no birth awaiting acknowledgement") {
        throw new Error("unexpected message: " + JSON.stringify(msg.textContent));
      }
      if (confirmBtn.disabled) {
        throw new Error("confirm button should be re-enabled after failed request");
      }
    }
  },
  {
    name: "script tags render as text via textContent",
    setup: function (sandbox) {
      makePanelElements(sandbox);
      sandbox._setResponse({
        status: 200,
        json: async function () {
          return {
            pending: false,
            request_id: null,
            development: {
              stage: "<script>alert(1)</script>",
              readiness: { ready: false, passed: ["<script>"], unmet: [] },
              readout: { "<script>": "evil" }
            }
          };
        }
      });
    },
    run: async function (sandbox) {
      await tick();
      var stage = sandbox.document.getElementById(STAGE_ID);
      var readiness = sandbox.document.getElementById(READINESS_ID);
      if (stage.textContent !== "<script>alert(1)</script>") {
        throw new Error("stage should contain literal script tag text");
      }
      if (readiness.textContent.indexOf("<script>") === -1) {
        throw new Error("readiness should contain literal script tag text");
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
      if (sandbox._visibilityCalls[0].ms !== 5000) {
        throw new Error("expected interval 5000, got " + sandbox._visibilityCalls[0].ms);
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
