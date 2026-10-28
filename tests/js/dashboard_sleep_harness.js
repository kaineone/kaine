const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(ROOT, "kaine", "dashboard", "static", "dashboard_sleep.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

const TEXT_IDS = [
  "sleep-state", "sleep-trigger", "sleep-started", "sleep-duration",
  "sleep-rest-length"
];
const HIDDEN_IDS = ["sleep-aborted"];

// The dashboard reads Date.now() for "time so far". The sandbox gets a Date whose now() is
// fixed, so no case depends on how slow the runner is.
const NOW_MS = 1800000000000;
class FixedDate extends Date {
  static now() { return NOW_MS; }
}

function makeSandbox(payload) {
  var elements = {};
  TEXT_IDS.forEach(function (id) {
    elements[id] = { id: id, textContent: "n/a", hidden: false };
  });
  HIDDEN_IDS.forEach(function (id) {
    elements[id] = { id: id, textContent: "", hidden: id === "sleep-aborted" };
  });
  var sandbox = {
    window: undefined,
    document: {
      readyState: "complete",
      addEventListener: function () {},
      getElementById: function (id) { return elements[id] || null; }
    },
    fetch: function () {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async function () { return payload; }
      });
    },
    Promise: globalThis.Promise,
    Date: FixedDate,
    Math: globalThis.Math,
    JSON: globalThis.JSON,
    Object: globalThis.Object,
    String: globalThis.String,
    isNaN: globalThis.isNaN,
    isFinite: globalThis.isFinite,
    console: globalThis.console,
    setInterval: function () {},
    _elements: elements
  };
  sandbox.window = sandbox;
  vm.runInNewContext(source, sandbox, { filename: "dashboard_sleep.js" });
  return sandbox;
}

function tick() {
  return new Promise(function (resolve) { setTimeout(resolve, 0); });
}

function expectEqual(sandbox, id, expected) {
  var got = sandbox._elements[id].textContent;
  if (got !== expected) {
    throw new Error(id + ": expected " + JSON.stringify(expected) + " got " + JSON.stringify(got));
  }
}

function expectHidden(sandbox, id, expected) {
  if (sandbox._elements[id].hidden !== expected) {
    throw new Error(id + ": expected hidden=" + expected);
  }
}

var scenarios = [
  {
    name: "completed state-cycle rest",
    payload: {
      sleeping: false,
      sleep: {
        asleep: false, trigger: "state_cycle", started_at: 1000,
        duration_s: 1415, rest_seconds: 1410, aborted: false, completed_at: null
      },
    },
    check: function (s) {
      expectEqual(s, "sleep-state", "awake");
      expectEqual(s, "sleep-trigger", "state-cycle rest");
      expectEqual(s, "sleep-duration", "23 min 35 s");
      expectEqual(s, "sleep-rest-length", "23 min 30 s");
      expectHidden(s, "sleep-aborted", true);
    }
  },
  {
    name: "asleep shows time so far",
    payload: {
      sleeping: true,
      sleep: {
        asleep: true, trigger: "requested",
        started_at: NOW_MS / 1000 - 60,
        duration_s: null, rest_seconds: null, aborted: false, completed_at: null
      },
    },
    check: function (s) {
      expectEqual(s, "sleep-state", "asleep");
      expectEqual(s, "sleep-trigger", "requested");
      var d = s._elements["sleep-duration"].textContent;
      if (d !== "1 min 0 s so far") {
        throw new Error("duration: got " + JSON.stringify(d));
      }
      expectEqual(s, "sleep-rest-length", "n/a");
    }
  },
  {
    name: "fatigue or backstop label",
    payload: {
      sleeping: false,
      sleep: {
        asleep: false, trigger: "fatigue_or_backstop", started_at: null,
        duration_s: 30, rest_seconds: null, aborted: false, completed_at: null
      },
    },
    check: function (s) {
      expectEqual(s, "sleep-trigger", "fatigue or backstop (not stated)");
      expectEqual(s, "sleep-started", "n/a");
      expectEqual(s, "sleep-duration", "30 s");
    }
  },
  {
    name: "aborted sleep is flagged",
    payload: {
      sleeping: false,
      sleep: {
        asleep: false, trigger: "backstop", started_at: null,
        duration_s: 1, rest_seconds: null, aborted: true, completed_at: null
      },
    },
    check: function (s) {
      expectEqual(s, "sleep-trigger", "backstop (an hour awake)");
      expectHidden(s, "sleep-aborted", false);
    }
  },
  {
    name: "an earlier-rule developmental rest keeps a label",
    payload: {
      sleeping: false,
      sleep: {
        asleep: false, trigger: "developmental_rest", started_at: 1000,
        duration_s: 1265, rest_seconds: 1260, aborted: false, completed_at: null
      }
    },
    check: function (s) {
      expectEqual(s, "sleep-trigger", "developmental rest (earlier rule)");
      expectEqual(s, "sleep-rest-length", "21 min 0 s");
    }
  },
  {
    name: "null sleep gives n/a",
    payload: { sleeping: false, sleep: null },
    check: function (s) {
      expectEqual(s, "sleep-state", "awake");
      expectEqual(s, "sleep-trigger", "n/a");
      expectEqual(s, "sleep-started", "n/a");
      expectEqual(s, "sleep-duration", "n/a");
      expectEqual(s, "sleep-rest-length", "n/a");
      expectHidden(s, "sleep-aborted", true);
    }
  },
  {
    name: "helpers",
    payload: { sleeping: false, sleep: null },
    check: function (s) {
      var api = s.window.DashboardSleep;
      if (api.triggerLabel(null) !== "not known") throw new Error("null label");
      if (api.triggerLabel("weird") !== "not known") throw new Error("other label");
      if (api.formatDuration(null) !== "n/a") throw new Error("null duration");
      if (api.formatDuration(12.4) !== "12 s") throw new Error("short duration");
    }
  }
];

async function main() {
  var failures = [];
  if (source.indexOf("innerHTML") !== -1) {
    failures.push("source uses innerHTML");
  }
  for (var i = 0; i < scenarios.length; i++) {
    var sc = scenarios[i];
    try {
      var sandbox = makeSandbox(sc.payload);
      await tick();
      await tick();
      sc.check(sandbox);
    } catch (err) {
      failures.push(sc.name + ": " + err.message);
    }
  }
  if (failures.length) {
    process.stdout.write(JSON.stringify({ ok: false, failures: failures }) + "\n");
    process.exit(1);
  }
  process.stdout.write(JSON.stringify({ ok: true }) + "\n");
}

main().catch(function (err) {
  process.stdout.write(JSON.stringify({ ok: false, failures: [err.message] }) + "\n");
  process.exit(1);
});
