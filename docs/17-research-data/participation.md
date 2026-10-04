# Research participation

Operators and researchers share KAINE session telemetry through the research CLI. This page explains what research data is collected, how it stays private, how to review and submit it, and the optional local-only event logs. Sharing is opt-in and operator-initiated: nothing leaves the host unless you run the send command.

## Privacy guarantees

The default research bundle is numeric metrics only. It contains:

| Included | Excluded (never) |
|---|---|
| A/B divergence scores (cosine divergence, numeric) | Lingua intent log (`state/lingua/intent_expression.jsonl`) — embeds user/bystander utterances and the entity's internal monologue. |
| Individuation evidence (encrypted welfare evidence under `state/individuation/`; whether content-free reports are exported in research bundles is an open operator decision, and those reports are not in research bundles today) | Mnemos/Qdrant memories — verbatim transcripts and episodic records. |
| Coherence PLV time series (numeric) | Eidolon self-model (`state/eidolon/self_model.json`) — identity history. |
| Welfare / gray-zone event counts (numeric) | Conversation content (any turn text). |
| Fatigue accumulator series (numeric) | Replay logs (may contain verbatim memory text when `replay_redact_content = false`). |
| Prediction-error series (numeric) | Raw bus archive (`state/research/raw_bus_archive/`) — verbatim events, including conversation content. |
| Nous policy logs (numeric) | External-utterance log and Nexus record — local-only, never exported. |
| Voice-alignment divergence (numeric) | |
| Curated research event log (`data/evaluation/research_events/`) — privacy-filtered numeric/categorical records | |
| Per-run manifest files (`runs/`) | |
| `manifest.json` enumerating every included file | |

### How the privacy guarantee is enforced in code

The bundle builder in `kaine/research/submission.py` is allowlist-based. It copies only the directories named in `METRICS_ONLY_DIRS`, so a new sensitive sink cannot leak into the bundle by accident. The `runs/` directory is in that allowlist. A denylist adds a second layer.

### Content preview before any send

The CLI always prints a complete inventory — file paths, line counts, and a sample line per file — before asking for confirmation. When state encryption is enabled, `--preview` encrypts the bundle as it builds it; the output directory then holds only `manifest.json` and `bundle.tar.enc`. The printed inventory is what you review.

### Encryption

The shipped config enables `[security.state_encryption]` by default. The bundle builder encrypts the data with AES-256-GCM inside `build_research_bundle`, before the preview is printed. If the key is unavailable, the CLI exits with an error before building anything; there is no plaintext fallback. The email carries only the local bundle path, never the bundle itself.

### Operator-initiated only

There is no scheduled or background submission. The only transmission path is:

1. Run `python -m kaine.research --preview` to build the bundle and print the inventory. Nothing is sent.
2. Run `python -m kaine.research --send` to build the bundle, print the inventory, and ask for confirmation. If a recipient is configured, the prompt is a single `Send metrics bundle to …? [y/N]`. If no recipient is configured, it prompts for one and then asks to confirm. The bundle is already encrypted at this point if encryption is enabled. The CLI then sends via SMTP or writes `research_out/transfer_request.eml` and a `mailto:` link.

The builder also checks the run's [admissibility gate](../16-run-identity.md). If the run is inadmissible, export is blocked unless you pass `--admissibility-override-reason "..."`.

## The research event log

KAINE's event bus is a capped Redis Streams ring buffer; entries are trimmed within minutes to hours. The Redis service in `compose/kaine.yml` runs with AOF persistence on but RDB snapshots disabled.

To answer session-spanning research questions, there is an opt-in durable event log with several independent sinks. See the [event streams page](./event-streams.md) for the stream registry details.

### Curated research event log (export-eligible)

`[research_event_log]` ships disabled. When enabled, a `ResearchEventObserver` subscribes to a curated allowlist of bus streams and writes one privacy-filtered record per relevant event to an encrypted, daily-rotated JSONL sink under `data/evaluation/research_events/`.

- Each record carries `ts` (ISO-8601 UTC), `event_type`, `source`, and `tick_index`/`incident_id` when present, plus only the numeric/categorical fields named in the per-type allowlist. Event types not in the taxonomy produce no record at all.
- Every record passes `PrivacyFilter.filter_for_diagnostics()` before field extraction, stripping `CONTENT_FIELDS`: `text`, `body`, `content`, `internal_speech`, `belief_text`, `memory_text`, `affect_reason`, `transcription`, `user_input`, `faithful_rendering`, `description`, and `statement`. Per-type redaction then removes additional sensitive fields.
- It never logs raw audio or video (`mundus.visual.raw`, PCM), `audition.transcription` text, Lingua intent content, memory text, the Eidolon self-model, conversation content, or operator host/IP/voice. Avatar proprioception is logged only as an opaque position hash plus a region label — never raw coordinates.
- Each line is encrypted at rest through the shared `AsyncJsonlSink` + `StateEncryptor` mechanism.
- Because `research_events` is in `METRICS_ONLY_DIRS`, an operator-initiated metrics bundle can include it.
- It runs on its own `[research_event_log].enabled` flag, independent of `[evaluation].enabled`.

### Local-only raw bus archive (never exported)

`[research_event_log.raw_archive]` ships disabled. When enabled, a `RawBusArchiveConsumer` tees verbatim events from every `<module>.out` stream to `state/research/raw_bus_archive/` for deep local analysis. This data includes conversation content and transcripts, so it is locked down:

- It writes outside `data/evaluation/`, so the metrics bundle builder can never include it.
- It is encrypted at rest through the same `AsyncJsonlSink` + `StateEncryptor` mechanism.
- It requires `enabled = true` plus both `entity_privacy_attested = true` and `bystander_consent_attested = true`. If either attestation is false, `RawBusArchiveConsumer.start()` raises `RawArchiveAttestationError`, logs an error, and nothing starts.

### External-utterance log (local only)

`[research_event_log.external_utterances]` ships disabled. It subscribes only to `lingua.external` and writes one record per external speech event: the entity's spoken text and its timestamps. It lands in `state/research/external_utterances/` on the `kaine-state` volume. It never records inner speech (`lingua.internal` is not subscribed), bystander input, or anything the privacy filter removes. Files are encrypted at rest when state encryption is on. `retention_days = 0` keeps records forever. This sink is local only and never part of the research bundle.

### Nexus record (local only)

`[research_event_log.nexus_record]` ships disabled. It subscribes to the streams the Nexus bridge reads and writes exactly the payload Nexus displays after its privacy filter, with numeric vectors removed, plus the stream name and entry id. It lands in `data/nexus_record/` on the `kaine-nexus-record` volume. Studies never enable it. Files are encrypted at rest when state encryption is on. `retention_days = 0` keeps records forever. This sink is local only and never exported.

### Ignition log (local only)

The ignition log is an optional, disabled-by-default per-broadcast research record configured in `[ignition_log]`. The cycle writes one JSONL record for every successful workspace broadcast. Each record contains:

- the run id and a per-sink sequence number;
- the tick index and the broadcast's bus entry id;
- wall and monotonic timestamps of the broadcast;
- the programme position at that instant: item index, order, title, offset in seconds, whether the programme was paused, and the pause holders (`paused_by`);
- the audio feed's delivered position (item index and seconds handed to the listener) when a playlist stream is running, so picture/sound drift is measurable;
- the salience scores and inhibition decision;
- each coalition member's entry id, source, type, salience, and original timestamp.

The log never records event payloads, so no conversation content, transcripts, video frames, or audio samples are persisted. It is not placed on the bus and no module receives it. Records are encrypted at rest when state encryption is on, never auto-purged, and never exported. The module-ignition study turns this and the other local recorders on; see [the ignition study page](../15-experiments/ignition-study.md) for more.

The programme clock pauses while the cycle is frozen (holder `freeze`) and while Hypnos holds a replay window (holder `hypnos`), so the film resumes where the entity left it. It is held at zero under `transition` while a born being's viewing opens with the womb-to-world crossfade. Each record names the current pause holders in `paused_by`, for example `["transition"]` or `["hypnos", "transition"]`, so analysis can tell the crossfade from sleep or a freeze.

## Media voices

Heard audio is tagged with the channel it arrived on: `live_mic` for the microphone, `remote` for remote audio, and `playlist`, `seeded`, `womb`, or `screen` for the matching perception feed. Empatheia attributes operator channels to the configured speaker label and attributes every other channel to its own `media:<channel>` agent, so film dialogue does not shape the operator model. Volition treats only operator-channel transcriptions as speech addressed to the entity.

## How to enable and submit

Put local changes in the gitignored `config/kaine.operator.toml` overlay; do not edit the tracked `config/kaine.toml`.

### 1. Configure the recipient

```toml
[research_submission]
enabled = true
recipient = "kaine.one@tuta.com"
tier = "metrics"
```

The shipped default is `enabled = false` and `recipient = ""`. The `enabled` flag does not block `--send`: KAINE has no automatic submission, so the real gate is running `--send` and confirming. If `recipient` is empty, the CLI falls back to `[transfer].recipient` and prompts only if that is also empty. The submission reuses the `[transfer]` SMTP settings. If SMTP is not configured, the CLI writes `transfer_request.eml` and a `mailto:` link for you to send from your own client.

For the optional Claude Science export, use `python -m kaine.research --claude-science`, controlled by `[research_submission.claude_science]`.

### 2. Preview the bundle

```bash
python -m kaine.research --preview
```

This builds the bundle in `research_out/research_bundle_<UTC>/` and prints the inventory. When state encryption is enabled, the directory contains only `manifest.json` and `bundle.tar.enc`; the inventory is the review surface. Nothing is sent.

### 3. Send the bundle

```bash
python -m kaine.research --send
```

The CLI builds the bundle, prints the preview, and asks for confirmation. If a recipient is configured, the prompt is a single `Send metrics bundle to …? [y/N]`. If no recipient is configured, it prompts for one and then asks to confirm. The bundle is encrypted during the build if encryption is enabled. The CLI then sends via SMTP or writes `research_out/transfer_request.eml` and a `mailto:` link.

Full configuration keys are in the [configuration reference](../appendix-a-configuration/lifecycle-and-research.md).

## What happens with the data?

The project uses the numeric metrics to:

- verify that the architecture produces divergent, individuated cognitive behaviour across fork lineages;
- study the welfare signal distribution, including gray-zone event frequency and fatigue patterns;
- improve the evaluation instruments and publish results.

No entity content — no speech, no memories, no inner monologue — is transmitted or used for any other purpose.

## Frequently asked questions

**Do I have to participate?** No. KAINE has no scheduled or background submission. Nothing leaves the host unless you run `python -m kaine.research --send` and confirm. Setting `[research_submission].enabled = false` only reflects the shipped default; it does not prevent a manual send.

**Can I review exactly what is sent?** Yes. `--preview` always runs first and prints a line-by-line inventory. When state encryption is enabled, the bundle is encrypted during preview and the output directory contains only `manifest.json` and `bundle.tar.enc`; the printed inventory is what you review.

**What if SMTP is not configured?** The CLI writes `research_out/transfer_request.eml` and a `mailto:` link. You send it from your own email client.

**Where does the bundle go?** The email carries only the local path and a short note. Nothing is uploaded automatically.

**Is the bundle encrypted?** Yes, when state encryption is enabled and a key is available. If the key is unavailable, the CLI exits before building the bundle. The email carries only the local path, not the bundle.

**Can I submit an inadmissible run?** No, unless you pass `--admissibility-override-reason "..."`. The bundle builder blocks export of inadmissible runs by default.
