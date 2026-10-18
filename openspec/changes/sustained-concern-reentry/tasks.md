## 1. Implementation

- [x] 1.1 Republish an active goal's drive event every `P_re` while its drive is at or above threshold, at intensity `D`, unmarked as an alert, recorded among the drive entry ids; clear the schedule when the goal ends and on the sleep reset
- [x] 1.2 Wire `[affect] concern_reentry_s` (default 30.0, finite and >= 0, 0 off) through the constructor, the factory and `config/kaine.toml`
- [x] 1.3 Keep the `reentry` field in the research log, count only crossings in the self-model, and describe a re-entry in the faithful template
- [x] 1.4 Tests: cadence and intensity; no re-entry below threshold or without an active goal; stops on goal end, stall and sleep reset; intents about a re-entry do not relieve boredom; not an alert; 0 is identical to the previous build; validation and config wiring
- [x] 1.5 Update `docs/09-modules/affect.md`
