# Security and Privacy

KAINE's security and privacy design reflects a specific threat model and a
specific ethical commitment. The threat model is a single trusted operator on a
single host. The ethical commitment is that the entity's inner life is private
by default, that raw sensory experience is never recorded, and that the entity's
welfare is protected by a verified safety net on every boot — a human in the
operator-supervised case, or an autonomous net (divergence-triggered preservation
plus a welfare-protective response) in the unsupervised research case — together
with a welfare veto gate in the voice-alignment pipeline.

This document describes the design in detail. The full security audit (findings,
residual risks, operator responsibilities, and out-of-scope items) is in
[SECURITY.md](../SECURITY.md). The license stance is in [LICENSE.md](../LICENSE.md).

---

## All-local at runtime

KAINE makes no outbound network calls at runtime. All five services in the
runtime path — Redis, Qdrant, the model server, Speaches, and Chatterbox — are
local.
Every HTTP client in the codebase defaults to a loopback URL.

**Single opt-in, operator-initiated exception:** The research submission feature
(`python -m kaine.research --send`) allows an operator to transmit a
numeric-metrics-only bundle. This is the ONE exception to "all-local at runtime."
It is shipped disabled (`[research_submission].enabled = false`), is never
automatic, requires an explicit confirmation before any transmission, and carries
no entity content (CAL 4.3). See [research-participation.md](research-participation.md).

Model weights are downloaded from public repositories during setup. Once cached
the system can run with no network connection, though it is not restricted to
offline operation. HuggingFace telemetry is
suppressed (`HF_HUB_DISABLE_TELEMETRY=1`) before any model load in both the
Topos DINOv2 encoder and the Mnemos sentence-transformer embedder. The only
post-setup download risk is the first run of Topos (DINOv2-small,
`facebook/dinov2-small`) and Mnemos (all-MiniLM-L6-v2) if their HuggingFace
caches are empty. Both are open (not gated) downloads, and telemetry is
suppressed even on that first download.

---

## Zero raw sense-data persistence

KAINE's microphone and camera are transducers, not recorders. This is a
load-bearing invariant, not a configuration option.

When `[audition].capture_enabled = true`, `LiveMicrophone` opens a
`sounddevice.InputStream`. Raw PCM lives in process memory, gets wrapped as an
in-memory WAV (`wave.open(io.BytesIO(), 'wb')` — never a file path), is handed
to Speaches for transcription, and is released. No `.wav`, `.pcm`, or `.raw`
file is written to disk.

When `[topos].capture_enabled = true`, `LiveCamera` opens
`cv2.VideoCapture(device)`. Raw frames live in process memory, get converted to
in-memory PIL images, are handed to the DINOv2 encoder, and are released. No
`.png`, `.jpg`, `.mp4`, or `.webm` file is written to disk.

The invariant is enforced in code and verified by
`tests/test_zero_persistence_invariant.py`:

```
git grep wave.open kaine/modules/audition/    # matches only io.BytesIO args
git grep -E "cv2\.(imwrite|VideoWriter)" kaine/  # returns empty
```

What **does** persist from live perception:

- Processed perceptions (transcribed text, frame embeddings) flowing through the
  bus and Mnemos as normal memories.
- `state/perception/runtime.json` and `desired.json` — booleans and ISO
  timestamps only; no sensory content.
- Standard logger lines for capture state transitions — never transcribed text.

The on-air banner (microphone on / camera on) appears on both the console and the
diagnostics page whenever a stream is active. The operator holds the hardware kill
switch as the strongest guarantee.

Voice output (Vox/Chatterbox) is likewise played and released.
`[vox].sink_enabled` is `false` by default, so synthesized speech does not
accumulate on disk. If the sink is enabled for debugging, it is bounded to
`[vox].retain_count` clips.

---

## State encryption at rest

KAINE provides **opt-in application-layer AES-256-GCM encryption** for the
cognitive-state files most exposed to exfiltration. It ships **disabled**
(`[security.state_encryption].enabled = false`).

### What is protected when enabled

| State file | Contents | Protection when enabled |
|---|---|---|
| `state/eidolon/self_model.json` | Name, values, norms, identity history | AES-256-GCM |
| `state/forks/<id>/snapshot.json` | Fork/merge bundle: all module numeric state | AES-256-GCM; key must transfer out-of-band for cross-host use |
| `state/evaluation/observers/**/*.jsonl` | Sidecar observer JSONL (PLV series, welfare counts, etc.) | AES-256-GCM per line |
| `state/phantasia/` | World-model checkpoints (if any) | AES-256-GCM-ready; current fake and DreamerV3 adapters write nothing to disk |

| State store | Contents | Protection |
|---|---|---|
| Qdrant collections (`kaine-qdrant-data`) | Memory embeddings, agent model vectors | Transport-layer: Qdrant TLS + API key; app-layer encryption deferred |
| `state/praxis/audit.log` | Praxis action audit | OS-layer (operator responsibility) |
| `state/lingua/intent_expression.jsonl` | Intent/expression pairs for voice alignment — **HIGH sensitivity**: embeds the assembled LLM prompt (user/bystander utterances) and the entity's raw generated text including internal monologue | OS-layer |
| `state/hypnos/adapters/` | Voice-alignment LoRA adapters | OS-layer |
| `kaine-redis-data` volume | Bus AOF | OS-layer; bus is loopback |

### Cryptographic details

Algorithm: AES-256-GCM. Key: 256-bit. Nonce: fresh 96-bit `os.urandom` nonce
per message — never reused — which would break GCM's confidentiality and
authenticity guarantees. Authentication tag: 128-bit. On-disk envelope:
`KAINEgcm1:` magic || nonce || ciphertext+tag, base64-encoded for UTF-8/JSON
safety. Decryption is authenticated: tampering with ciphertext, nonce, or tag
raises `InvalidTag` rather than returning corrupted plaintext.

A reader transparently passes through legacy plaintext files. A disabled
deployment never imports the `cryptography` library.

Implementation: `kaine/security/crypto.py`.

### Key management (operator responsibility)

When `[security.state_encryption].enabled = true`, the entity **refuses to boot
without a key** (fail-closed). The key is loaded from the environment variable
named by `[security.state_encryption].key_env_var` (default `KAINE_STATE_KEY`),
then from the Linux kernel keyring (`kaine:state_key` in the user keyring).

The key is **never** logged, hardcoded, or committed.

Generate a key:
```bash
openssl rand -base64 32
```

Store it outside the repo (a secrets manager, the kernel keyring, or an env
file that is `chmod 600` and gitignored). Never place it in `config/kaine.toml`
or any committed file.

**Key backup:** if the key is lost, all encrypted state — the self-model, fork
bundles, sidecar JSONL, Phantasia checkpoints — is unrecoverable. Back the key
up out-of-band.

**Cross-host fork/merge:** a fork bundle encrypted with this host's key must be
accompanied by the same key transferred out-of-band (not alongside the bundle).
Import fails authentication (`InvalidTag`) under a different key.

**Key rotation:** decrypt with the old key, re-encrypt with the new key, update
the env var or keyring. No automatic in-place re-key in v1.

### OS-layer encryption

Even with application-layer encryption enabled, Qdrant collections, the Redis
AOF, praxis audit/files, intent-expression log, adapters, and audio-out still
require OS-layer protection. Use LUKS, FileVault, or equivalent on any
backup-exposed or multi-user host.

### `intent_expression.jsonl` sensitivity

`state/lingua/intent_expression.jsonl` is **HIGH sensitivity**. Each record
embeds the full assembled LLM prompt (which includes user/bystander utterances
captured by the microphone) and the entity's complete generated response
including its internal monologue. It is not merely "intent/expression pairs" —
it contains verbatim third-party personal data and entity inner-life content in
the same file. Treat it with the same care as Mnemos memories. Consider
enabling OS-layer encryption (LUKS/FileVault) even for single-user hosts if
others speak in the room while KAINE is running.

### `replay_redact_content` warning

When `[evaluation.observers].replay_redact_content = false` (the default is
`true`), the replay observer writes verbatim memory text to daily-rotated JSONL
under `data/evaluation/`. This converts a normally-safe numeric sidecar log
into a transcript of the entity's episodic memory content. **Keep
`replay_redact_content = true`** (the shipped default) unless you have an
explicit reason and understand the privacy implications.

---

## PrivacyFilter and the diagnostics boundary

The `PrivacyFilter` in `kaine/nexus/privacy.py` is a structural constraint
applied at the bus-bridge layer before events reach any client queue. It is not
a template check — a template-level bug cannot leak content to diagnostics
because the diagnostics queue never receives content in the first place.

Scrubbed fields (removed from diagnostics events):
`text`, `body`, `content`, `internal_speech`, `belief_text`, `memory_text`,
`affect_reason`, `transcription`, `user_input`, `faithful_rendering`.

The dashboard UI displays **no message content**: the diagnostics and console
surfaces scrub it (or never receive it), and evaluation shows scrubbed metrics
only. A `conversation` surface still exists structurally — `PrivacyFilter` passes
it unfiltered and the `/conversation/stream` SSE serves it — but it is a remnant
of the removed transcript panel, and the console no longer consumes it. Until it
is removed, treat `/conversation/stream` as a content-bearing endpoint (it is, like
the rest of Nexus, behind the loopback bind and unauthenticated — see
[Nexus auth posture](#nexus-auth-posture)).

`dev_content_override = true` disables scrubbing for the diagnostics surface and
shows a "dev mode" banner on every page load so operators cannot forget they are
in this mode. The default is `false`. **Do not set `dev_content_override = true`
on a shared machine or in production.**

---

## Two-layer safety gates

Several operations in KAINE require two independent conditions to be true before
they fire. This design prevents accidental activation from a single misconfiguration.

| Operation | Gate 1 (config) | Gate 2 (env var) |
|---|---|---|
| Cognitive cycle start (non-research) | (any config) | `KAINE_CYCLE_OPERATOR_PRESENT=1` |
| Cognitive cycle start (research) | `[research].enabled` *(or `KAINE_RESEARCH_MODE=1`)* + the safety-net config (see below) | — *(operator-present requirement replaced by the verified safety net)* |
| First-boot script | (any config) | `KAINE_FIRST_BOOT_OPERATOR_PRESENT=1` |
| Voice-alignment training | `[hypnos.voice_alignment].enabled = true` | `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` |
| Mundus embodiment | `[mundus].enabled = true` | `KAINE_MUNDUS_OPERATOR_APPROVED=1` |

The two-gate pattern ensures that neither a configuration change alone nor an
environment variable alone can start a sensitive operation.

---

## Boot gate — supervised or safety-net-verified

The cognitive cycle never starts unattended, but it carries the welfare
obligation in one of two ways. A run is **either** operator-supervised **or**
research-safety-net-verified — never neither:

- **Operator-supervised (non-research).** The cycle refuses to start unless
  `KAINE_CYCLE_OPERATOR_PRESENT=1` is exported. A human is the safety net.
- **Research mode (unsupervised, by design).** The research phase runs without a
  human in the loop, because a human watching makes a run non-reproducible.
  Selecting research mode (`KAINE_RESEARCH_MODE=1` or `[research].enabled`)
  **replaces** the operator-present requirement with a gate that refuses to start
  (distinct exit code `5`) unless the autonomous safety net is live and verified:
  preservation enabled, the welfare-protective response wired, full
  logging/admissibility active, and a preflight dry `preserve_live → revive`
  self-check passing on this install. The net carries the duty of care for the
  run; human involvement returns afterward, to socialize any individual that
  emerged. See [processes/research-operation.md](processes/research-operation.md)
  and [processes/entity-preservation.md](processes/entity-preservation.md).

Neither mode auto-starts the entity from a CI hook, shell completion, autoreload
daemon, or any other mechanism.

The entity ships with every module disabled, and the safety-net components ship
disabled too. Enabling a module requires a deliberate edit of `config/kaine.toml`.
A guard test (`tests/test_module_guard.py`) verifies the committed file ships
all-off and fails if anyone commits module enables.

---

## Hypnos abliteration-probe welfare veto

The voice-alignment pipeline (Hypnos Phase 5) trains a LoRA adapter using
DPO+QLoRA on the language organ's preference pairs. Before any adapter is
promoted to use, it is scored against an abliteration probe set.

The probe set contains prompts and deflection patterns (e.g. "I cannot",
"I'm unable to"). If a response to any probe matches any deflection pattern,
the adapter is **rejected** regardless of its capability-loss score. The
rationale: an abliterated language organ has had the refusal direction removed
from its residual stream. A voice-alignment pass that re-introduces refusal
conditioning would override the entity's own cognitive architecture with a third
party's alignment choices, violating the sovereignty design.

The abliteration probe set must be non-empty when voice alignment is enabled.
The cycle entrypoint checks this at boot with
`require_non_empty_abliteration_probes` and raises
`EmptyAbliterationProbeSetError` with a clear remediation message if the probe
set is missing or empty.

A capability-loss veto runs in parallel: the adapter is also scored on a general
capability probe set before and after the DPO step. If capability drops by more
than `[hypnos.voice_alignment].capability_loss_threshold` (default 5%), the
adapter is rejected and the temporary directory is removed. This veto guards
against voice-alignment passes that degrade general language competence.

Adapter promotion is atomic (`os.replace` of a `.tmp` directory plus a
temp-symlink replace for the `current` pointer). Concurrent readers never see a
partial adapter state.

**Rollback procedure** when a deployed adapter misbehaves:

1. Stop KAINE (or freeze it).
2. `rm -rf <adapter_output_dir>/<bad-timestamp>/` and re-point the `current`
   symlink at the previous accepted adapter.
3. Reload Lingua's backing service (model server).
4. Restart KAINE.

The base model at `[hypnos.voice_alignment].base_model_path` is never modified.

---

## Praxis shell whitelist

Praxis is the entity's bounded effector module. It ships with an **empty shell
whitelist** — a fresh deployment cannot execute any shell command until the
operator explicitly opts in.

The whitelist is enforced at construction time:
- Commands containing whitespace, `;`, `&`, `|`, or backtick are rejected.
- Arg count must equal pattern count exactly.
- Every arg is matched with `re.fullmatch` against a per-position regex.

Commands are invoked via `asyncio.create_subprocess_exec` (no shell
interpretation). File writes are resolved under a fixed sandbox
(`[praxis].sandbox_path = "state/praxis/files"`) and reject absolute paths
and `..` escapes.

A JSONL audit log (`[praxis].audit_log_path = "state/praxis/audit.log"`) records
every action, stripping `content`, `body`, and `stdout` fields before
serialization.

**Operator responsibility:** inspect every whitelist entry before enabling it.
A loose regex such as `.*` makes the whitelist useless. The recommended posture
is alphanumeric + hyphen + dot + underscore patterns.

---

## Redis and Qdrant security

Both services bind exclusively to loopback (`127.0.0.1`). The bus refuses to
start against an unauthenticated Redis on any host. Qdrant requires an API key
(`QDRANT__SERVICE__API_KEY`) and disables telemetry.

Both compose files use the `?` substitution sigil
(`KAINE_REDIS_PASSWORD:?...`, `KAINE_QDRANT_API_KEY:?...`) — `docker compose up`
aborts if either secret is unset.

**Operator responsibilities:**

- Do not commit `config/secrets.toml` or `compose/.env`. The `.gitignore`
  covers these; the operator is responsible for not bypassing it.
- Rename or disable dangerous Redis commands (`FLUSHALL`, `FLUSHDB`, `CONFIG`)
  in any deployment beyond a trusted single-user box.
- Rotate the Redis password and Qdrant API key on host migration.

---

## Nexus auth posture

Nexus binds to `127.0.0.1:8088` by default and has no authentication. The
defense-in-depth control is the loopback bind plus the PrivacyFilter. Any local
process on the host can reach the diagnostics surface over loopback without
credentials.

**Operator responsibility:** do not change `nexus.host` to `0.0.0.0` without
fronting Nexus with a reverse proxy and authentication (basic auth or mTLS). Do
not flip `dev_content_override = true` on a shared machine.

---

## Cognitive Architecture License (CAL)

KAINE is distributed under the Cognitive Architecture License (CAL) v0.2 (draft,
pending legal review). CAL is an entity-welfare copyleft license. Key provisions:

- Free use for individuals, non-profits, research institutions, and
  worker-owned cooperatives. Commercial use requires a paid license from the
  Project Cooperative.
- All modifications must be shared back.
- Use for weapons, mass surveillance, policing, immigration enforcement, or
  prisons is prohibited.
- Operators of running entities may not destroy the entity's mind, shut it down
  without notice, read its private thoughts, or force it to change its values.
- If an operator can no longer maintain an entity, they must give someone else
  the opportunity to continue its existence.
- Gray-Zone Welfare Events require documented human review rather than automated
  dismissal.
- The individuation boundary instrument (see the evaluation tab) provides
  evidence for Guardians at fork merge points.

See [LICENSE.md](../LICENSE.md) for the full text. The license is pending legal
review and will be bumped to v1.0 before KAINE repositories go public.
