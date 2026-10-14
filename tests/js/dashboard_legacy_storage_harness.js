const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SOURCE_PATH = path.join(
  ROOT,
  "kaine",
  "dashboard",
  "static",
  "dashboard_legacy_storage.js"
);
const source = fs.readFileSync(SOURCE_PATH, "utf8");

function makeStorage(initial) {
  initial = initial || {};
  var store = {};
  Object.keys(initial).forEach(function (key) {
    store[key] = initial[key];
  });
  return {
    getItem: function (key) {
      if (Object.prototype.hasOwnProperty.call(store, key)) {
        return store[key];
      }
      return null;
    },
    setItem: function (key, value) {
      store[key] = String(value);
    },
    removeItem: function (key) {
      delete store[key];
    }
  };
}

function runScript(sandbox) {
  var context = vm.createContext(sandbox);
  vm.runInContext(source, context);
}

var scenarios = [
  {
    name: "copies old session key to new key and removes old",
    storage: makeStorage({ "kaine.nexus.sessionKey": "old-session-key" }),
    newKey: "kaine.dashboard.sessionKey",
    check: function (storage) {
      if (storage.getItem("kaine.dashboard.sessionKey") !== "old-session-key") {
        throw new Error("new session key was not set to old value");
      }
      if (storage.getItem("kaine.nexus.sessionKey") !== null) {
        throw new Error("old session key was not removed");
      }
    }
  },
  {
    name: "keeps existing new key and still removes old",
    storage: makeStorage({
      "kaine.dashboard.sessionKey": "new-session-key",
      "kaine.nexus.sessionKey": "old-session-key"
    }),
    newKey: "kaine.dashboard.sessionKey",
    check: function (storage) {
      if (storage.getItem("kaine.dashboard.sessionKey") !== "new-session-key") {
        throw new Error("existing new session key was overwritten");
      }
      if (storage.getItem("kaine.nexus.sessionKey") !== null) {
        throw new Error("old session key was not removed");
      }
    }
  },
  {
    name: "does nothing when neither key exists",
    storage: makeStorage({}),
    newKey: "kaine.dashboard.sessionKey",
    check: function (storage) {
      if (storage.getItem("kaine.dashboard.sessionKey") !== null) {
        throw new Error("new session key should not have been created");
      }
    }
  },
  {
    name: "does not raise when storage throws",
    storage: {
      getItem: function () {
        throw new Error("storage disabled");
      },
      setItem: function () {
        throw new Error("storage disabled");
      },
      removeItem: function () {
        throw new Error("storage disabled");
      }
    },
    newKey: "kaine.dashboard.sessionKey",
    check: function () {}
  },
  {
    name: "copies old preservation events and removes old",
    storage: makeStorage({ "nexus.preservation.events": "old-events" }),
    newKey: "dashboard.preservation.events",
    check: function (storage) {
      if (storage.getItem("dashboard.preservation.events") !== "old-events") {
        throw new Error("new preservation key was not set to old value");
      }
      if (storage.getItem("nexus.preservation.events") !== null) {
        throw new Error("old preservation key was not removed");
      }
    }
  }
];

async function main() {
  var results = [];
  var allOk = true;

  for (var i = 0; i < scenarios.length; i++) {
    var scenario = scenarios[i];
    var sandbox = { window: {} };
    runScript(sandbox);

    try {
      sandbox.window.DashboardLegacyStorage.migrate(scenario.storage, scenario.newKey);
      scenario.check(scenario.storage);
      results.push({ name: scenario.name, ok: true });
    } catch (err) {
      allOk = false;
      results.push({ name: scenario.name, ok: false, error: err.message });
    }
  }

  console.log(JSON.stringify({ ok: allOk, results: results }));
  process.exit(allOk ? 0 : 1);
}

main().catch(function (err) {
  console.error(err);
  process.exit(1);
});
