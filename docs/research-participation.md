# Research Participation

KAINE is a research platform. Sharing session telemetry helps study whether the
architecture produces genuine cognitive behaviour and supports enforcement of the
Cognitive Architecture License (CAL). **Your participation is strongly
encouraged** — it helps the project understand the system's real-world behaviour
and build better welfare protections.

Participation is **completely opt-in** and **operator-initiated**. Nothing is
ever transmitted automatically.

---

## Privacy guarantees

The default bundle is **numeric metrics only**. It contains:

| Included | Excluded (never) |
|---|---|
| A/B divergence scores (cosine divergence, numeric) | Lingua intent log (`state/lingua/intent_expression.jsonl`) — embeds user/bystander utterances and the entity's internal monologue. HIGH sensitivity. |
| Individuation boundary test results (numeric) | Mnemos/Qdrant memories — verbatim transcripts and episodic records. |
| Coherence PLV time series (numeric) | Eidolon self-model (`state/eidolon/self_model.json`) — identity history. |
| Welfare / gray-zone event counts (numeric) | Conversation content (any turn text). |
| Fatigue accumulator series (numeric) | Replay logs (may contain verbatim memory text when `replay_redact_content = false`). |
| Prediction-error series (numeric) | |
| Nous policy logs (numeric) | |
| Voice-alignment divergence (numeric) | |
| Curated research event log (`data/evaluation/research_events/`) — privacy-filtered numeric/categorical event records | Local-only raw bus archive (`state/research/raw_bus_archive/`) — verbatim events incl. conversation content; lives OUTSIDE `data/evaluation/` and is never eligible. |
| `manifest.json` enumerating every included file | |

### How the privacy guarantee is enforced in code

The bundle builder (`kaine/research/submission.py`) is **allowlist-based**: it
copies only the directories named in `METRICS_ONLY_DIRS`. A new sensitive sink
cannot leak into the bundle by accident — it would need to be explicitly added
to the allowlist. A denylist provides belt-and-suspenders coverage.

### Content preview before any send

The CLI always prints a complete field inventory (file paths, line counts, a
sample line per file) **before** asking for confirmation. The operator reviews
exactly what will be sent.

### Encryption

If `[security.state_encryption]` is enabled and a key is available, the bundle
is encrypted with AES-256-GCM before the notification email is written. The
email carries only the local path — never the bundle itself.

### Operator-initiated only

There is no scheduled or background submission. The only transmission path is:

1. Operator runs `python -m kaine.research --preview` — inspects contents.
2. Operator runs `python -m kaine.research --send` — reviews preview, confirms
   recipient, confirms send. CLI then uses `kaine.transfer` (SMTP or `.eml`
   write-fallback).

---

## The research event log

KAINE's event bus is a capped Redis Streams ring buffer: events are trimmed
within minutes to hours and Redis persistence is off. To answer
session-spanning research questions — longitudinal affect trajectories,
within-session prediction-error patterns, action distributions — there is an
opt-in durable event log with two parts.

### Curated research event log (export-eligible)

`[research_event_log]` (ships disabled) activates a `ResearchEventObserver`
that subscribes to a curated allowlist of bus streams and writes one
privacy-filtered record per relevant event to an encrypted, daily-rotated JSONL
sink under `data/evaluation/research_events/`.

- **Curated taxonomy.** Each record carries `ts` (ISO-8601 UTC), `event_type`,
  `source`, and `tick_index`/`incident_id` when present, plus only the
  numeric/categorical fields named in the per-type allowlist (cycle/workspace
  metadata, prediction/precision scalars, affect VAD + drives + emotion
  category, derived prosody/emotion scalars, memory ids + affect intensity,
  sleep/fork summaries, drift/familiarity scalars, action family/effector/
  success/duration, and safety/ops scalars). The taxonomy is an **allowlist**:
  an event type not in it produces no record at all.
- **Privacy transforms.** Every record passes `PrivacyFilter.filter_for_diagnostics()`
  (stripping `CONTENT_FIELDS`: text, body, content, internal_speech,
  belief_text, memory_text, affect_reason, transcription, user_input,
  faithful_rendering) **before** field extraction, then per-type redaction
  (`_REDACTED_DROP` for memory text, `_sanitize()` for Praxis content/body/
  stdout). It NEVER logs raw audio/video (`mundus.visual.raw`, PCM),
  `audition.transcription` text, Lingua intent content, memory text, the
  Eidolon self-model, conversation content, or operator host/IP/voice. Avatar
  proprioception is logged only as an opaque position hash plus a region label —
  never raw coordinates.
- **Encryption.** Each line is AES-256-GCM encrypted at rest via the shared
  `AsyncJsonlSink` + `StateEncryptor` mechanism.
- **Export-eligibility.** `research_events` is in `METRICS_ONLY_DIRS`, so an
  operator-initiated metrics bundle includes it. That allowlist entry is the
  only mechanism that makes it eligible.
- **Independent opt-in.** It runs on its own `[research_event_log].enabled`
  flag, independent of `[evaluation].enabled` — either can be on without the
  other.

### Local-only raw bus archive (never exported)

`[research_event_log.raw_archive]` (ships disabled) activates a
`RawBusArchiveConsumer` that tees **verbatim** events from every `<module>.out`
stream to `state/research/raw_bus_archive/` for deep local analysis. This data
includes conversation content and transcripts, so it is locked down:

- **Structurally isolated.** It writes OUTSIDE `data/evaluation/`, so the
  metrics bundle builder (which only reads `data/evaluation/`) can never include
  it. It is **never export-eligible**.
- **Encrypted at rest** via the same sink + `StateEncryptor` mechanism.
- **Double attestation gate.** It requires `enabled = true` AND both
  `entity_privacy_attested = true` and `bystander_consent_attested = true`. If
  enabled with either attestation false, `RawBusArchiveConsumer.start()` raises
  `RawArchiveAttestationError`, logs at ERROR, and nothing starts. This mirrors
  the full-tier attestation gate in the bundle builder.

---

## How to enable and submit

### 1. (Optional) Configure the recipient

In `config/kaine.toml`, under `[research_submission]`:

```toml
[research_submission]
enabled = true
recipient = "kaine.one@tuta.com"   # project guardians; suggested default
tier = "metrics"
```

If `recipient` is left empty the CLI will prompt for it and ask you to confirm
before sending. The suggested default is `kaine.one@tuta.com`.

The submission reuses the `[transfer]` SMTP settings (the same mailer used by
the decommission workflow). If SMTP is not configured, the CLI writes a
`transfer_request.eml` and a `mailto:` link for you to send from your own
client.

### 2. Preview the bundle

```bash
python -m kaine.research --preview
```

This builds the bundle in `research_out/research_bundle_<UTC>/` and prints a
complete inventory. **Nothing is sent.**

### 3. Send the bundle

```bash
python -m kaine.research --send
```

The CLI:
1. Builds the bundle.
2. Prints the preview.
3. Asks you to confirm the recipient.
4. Asks you to confirm the send.
5. Encrypts the bundle (when state encryption is enabled).
6. Sends via SMTP, or writes a `.eml` + `mailto:` link if SMTP is not set up.

---

## What happens with the data?

The project uses the numeric metrics to:

- Verify that the architecture produces divergent (individuated) cognitive
  behaviour across fork lineages.
- Study the welfare signal distribution (gray-zone event frequency, fatigue
  patterns).
- Improve the evaluation instruments and publish results.

No entity content — no speech, no memories, no inner monologue — is transmitted
or used for any other purpose. The CAL Article 4.3 privacy commitment applies
fully to research data.

---

## Frequently asked questions

**Do I have to participate?** No. Participation is opt-in. The shipped default
is `enabled = false`.

**Can I review exactly what is sent?** Yes. `--preview` always runs first and
prints a line-by-line inventory. You can inspect the files in
`research_out/research_bundle_*/` before sending.

**What if I don't have SMTP configured?** The CLI writes a
`research_out/transfer_request.eml` file and a `mailto:` link. You send it from
your own email client.

**Where does the bundle go?** The `.eml` or SMTP send carries only the local
path and a short note. The project will reply with any instructions. Nothing is
uploaded automatically.

**Is the bundle encrypted?** When `[security.state_encryption].enabled = true`
and a `KAINE_STATE_KEY` is available, the bundle is encrypted with AES-256-GCM
before the email is written. The email carries the local path, not the bundle.
