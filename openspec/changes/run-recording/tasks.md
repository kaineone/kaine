## 1. Observers
- [ ] 1.1 The external-utterance observer: it subscribes to `lingua.external` only, records `external_speech` (text and timestamps), and never records `user_input`. It writes through the encrypted JSONL sink to `state/research/external_utterances/`. It is off by default.
- [ ] 1.2 The Nexus-record observer: the same stream list and privacy filter as the Nexus bridge (a shared function, not a copy). It writes through the encrypted JSONL sink to `data/nexus_record/`. It is off by default.
- [ ] 1.3 Config keys in config/kaine.toml, wiring in the cycle, and exclusion from export (the metrics-only allowlist stays unchanged).

## 2. Study
- [ ] 2.1 The study overlay enables both logs, `[evaluation].workspace_trajectory` and `[ignition_log]`, and leaves the raw archive off.
- [ ] 2.2 The container deployment keeps both directories on durable volumes.

## 3. Verification
- [ ] 3.1 Tests:
  - an inner-speech event is never written;
  - an external utterance is;
  - the record equals the bridge's filtered payload;
  - a filtered field stays out;
  - neither path is export-eligible.
  A source-guard test proves no subscription to `lingua.internal`.
- [ ] 3.2 Docs (docs/operations.md, docs/security-and-privacy.md). The full offline suite is green.
