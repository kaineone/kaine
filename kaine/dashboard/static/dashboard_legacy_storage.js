// SPDX-License-Identifier: LicenseRef-CAL-0.4
// Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

(function () {
  "use strict";

  var OLD_KEYS = {
    "kaine.dashboard.sessionKey": "kaine.nexus.sessionKey",
    "dashboard.preservation.events": "nexus.preservation.events"
  };

  function migrate(storage, newKey) {
    try {
      var oldKey = OLD_KEYS[newKey];
      if (!oldKey) {
        return;
      }
      if (
        storage.getItem(newKey) === null &&
        storage.getItem(oldKey) !== null
      ) {
        storage.setItem(newKey, storage.getItem(oldKey));
      }
      if (storage.getItem(oldKey) !== null) {
        storage.removeItem(oldKey);
      }
    } catch (e) {
      // Storage may be missing or throw; migration is best-effort.
    }
  }

  window.DashboardLegacyStorage = {
    migrate: migrate,
    OLD_KEYS: OLD_KEYS
  };
})();
