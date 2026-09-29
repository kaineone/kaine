## Why

For each research run the operator wants "everything from Nexus recorded" and Lingua's external utterances, while inner thoughts stay private to the entity. Here is where things stand today.

**Already decided:**
- Inner speech is private. It is never shown, spoken or exported.
- Every diagnostic surface passes through `kaine/privacy_filter.py`.
- Claude Science receives only the metrics-only bundle.

**What persists today:**
- The research event log: content-free and allowlisted.
- The workspace trajectory: content-scrubbed, and off by default.
- The ignition log: off by default.

**The gaps:**
- **Lingua's external utterances are recorded nowhere.** The curated log excludes `lingua.out`, and the trajectory and Nexus strip text. The only verbatim path is the raw bus archive. It cannot separate inner from outer speech (`lingua.out` mirrors both), and it captures every module's content.
- **Nothing records what Nexus displays.** That is the privacy-filtered diagnostic streams the bridge sends to the browser.

## What Changes

- **External-utterance log.**
  - An opt-in, local-only log of the entity's external utterances: `external_speech` events from `lingua.external`, text included.
  - It never subscribes to `lingua.internal` and never records an `internal_speech` event.
  - It does not record `user_input` (bystander speech).
  - It is written through the existing encrypted JSONL sink to `state/research/external_utterances/`.
  - It is never export-eligible and not in the metrics-only bundle.
- **Nexus record.**
  - An opt-in, per-run record of every stream Nexus displays: the same stream list as the Nexus bridge (`diagnostics_streams()`), passed through the same privacy filter.
  - It is written by the cycle, so it exists whether or not a browser is open.
  - It uses the same encrypted JSONL sink, under `data/nexus_record/`. It is local-only and not export-eligible.
  - Expected size is about 2 GB per four-hour viewing, dominated by Topos's latent reports.
- **Study defaults.** The study overlay turns on both logs, `[evaluation].workspace_trajectory` and `[ignition_log]`. `[research_event_log.raw_archive]` stays off.
- **Unchanged.** The privacy filter, the research event log's allowlist, the Claude Science boundary, and zero raw-sense-data persistence.

## Capabilities

### Modified Capabilities
- `research-event-log`: adds the external-utterance log and the Nexus record, both local-only and never carrying inner speech.

## Impact

- **Code:**
  - two observers in `kaine/evaluation/observers/`, reusing `AsyncJsonlSink` and the stream-subscriber pattern;
  - config keys in `config/kaine.toml`;
  - the study overlay;
  - docs.
- **Privacy:** a source-guard test proves neither observer subscribes to inner speech.
