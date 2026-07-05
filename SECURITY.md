# KAINE Security Audit (v1.0)

Audit performed against the build prompt §9.2 checklist. This document captures
the security posture of KAINE as of v1: what is enforced in code, what is
documented as an operator responsibility, and what is explicitly deferred to
later versions.

KAINE is an all-local-runtime composite cognitive architecture. The v1 threat
model assumes a single trusted operator running on a single host. Multi-tenant,
network-attached, and cross-host deployments are out of scope for v1 but the
in-code defenses (Redis auth-on-loopback, sandboxed Praxis, gitignored secrets)
are designed so the same checkout remains safe when shipped to a hardened host
later.

## Reporting a Vulnerability

If you find a security vulnerability in KAINE, please report it **privately** so
it can be fixed before public disclosure. Do **not** open a public issue for a
security report.

- Preferred: GitHub private vulnerability reporting — the **Security → Report a
  vulnerability** button on this repository
  (`https://github.com/kaineone/kaine/security/advisories/new`).
- Or email **kaine.one@tuta.com** with a description and, if possible, a
  proof of concept.

This is a solo-maintained research project, so responses are best-effort: expect
acknowledgement within a few days, and we will coordinate a fix and a disclosure
timeline with you. Please allow reasonable time to remediate before disclosing
publicly. The remainder of this document is a security *audit* of the
architecture; the process above is how to report issues it does not cover.

## Scope

The audit covers six areas:

1. Redis bus auth and bind enforcement
2. Praxis shell whitelist and audit log
3. Container isolation (compose files)
4. State at rest (encryption posture)
5. Nexus auth posture and privacy boundary
6. External network calls in the runtime path

Code paths inspected:

- `kaine/bus/config.py`, `kaine/bus/client.py`, `kaine/bus/AUDIT.md`
- `kaine/modules/praxis/whitelist.py`, `kaine/modules/praxis/effectors.py`,
  `kaine/modules/praxis/audit_log.py`, `kaine/modules/praxis/AUDIT.md`
- `compose/redis.yml`, `compose/qdrant.yml`
- `scripts/redis-bootstrap.sh`, `scripts/qdrant-bootstrap.sh`
- `config/kaine.toml`, `config/secrets.example.toml`
- `kaine/nexus/app.py`, `kaine/nexus/config.py`, `kaine/privacy_filter.py`,
  `kaine/nexus/__main__.py`
- `.gitignore`, `pyproject.toml`

## Findings

### 1. Redis bus authentication and bind enforcement — HARDENED

The bus refuses to start against an unauthenticated Redis on any host.
`kaine/bus/config.py:110-116` raises `BusConfigError` from `load_bus_config()`
when no password is found in `KAINE_REDIS_PASSWORD`, `config/secrets.toml`
under `[redis].password`, or `config/kaine.toml`. The runtime audit in
`kaine/bus/client.py:89-129` then calls `CONFIG GET requirepass` and raises
`BusSecurityError` if the server reports it empty. For non-loopback hosts the
audit additionally calls `CONFIG GET bind` and refuses `0.0.0.0` / `*`
bindings (`client.py:98-113`). The bind check is intentionally relaxed on
loopback hosts because Docker port mapping
(`127.0.0.1:${KAINE_REDIS_HOST_PORT:-6479}:6379` in `compose/redis.yml:24`)
already enforces network isolation regardless of what Redis binds inside the
container. The `requirepass` check is never relaxed; rationale documented in
`kaine/bus/AUDIT.md` "Threat model" section. Residual risk: if Redis has had
the `CONFIG` command renamed/disabled, the audit logs a warning and continues
(`client.py:101-103, 116-118`); the operator then carries the verification
burden documented in row 1-5 of the `AUDIT.md` table.

### 2. Praxis shell whitelist and audit log — HARDENED

`kaine/modules/praxis/whitelist.py:23-57` rejects any command containing
whitespace, `;`, `&`, `|`, or backtick at whitelist construction time, refuses
duplicates, and matches every requested arg with `re.fullmatch` against a
per-position regex. Arg count must equal pattern count exactly
(`whitelist.py:52`). `kaine/modules/praxis/effectors.py:167-213` invokes
shell commands via `asyncio.create_subprocess_exec` (no shell interpretation),
applies a per-entry timeout (`wait_for` with kill on `TimeoutError`,
`effectors.py:190-197`), and never composes the command via string
concatenation. The default whitelist in `config/kaine.toml:178` is empty,
so a fresh deployment cannot execute any shell command until the operator
explicitly opts in. The file-write effector resolves every requested path
under a fixed sandbox (`_resolve_sandbox_path`, `effectors.py:61-71`) and
rejects absolute paths and `..` escapes. The audit log
(`kaine/modules/praxis/audit_log.py`) writes one JSONL record per action with
`os.O_APPEND` semantics (atomic for sub-PIPE_BUF lines, `audit_log.py:46-53`)
and strips `content`, `body`, and `stdout` fields before serialization
(`_FORBIDDEN_KEYS`, `audit_log.py:58`). Residual risk: an operator who adds a
permissive regex such as `.*` to a whitelist entry is responsible for the
consequences — the whitelist accepts loose patterns but the threat model in
`kaine/modules/praxis/AUDIT.md` "Whitelist invariants" calls this out.

### 3. Container isolation and restart posture — HARDENED

Both compose files publish exclusively to loopback. `compose/redis.yml:24`
binds the host side as `127.0.0.1:${KAINE_REDIS_HOST_PORT:-6479}:6379`, and
`compose/qdrant.yml:20` mirrors that with `127.0.0.1:${KAINE_QDRANT_HOST_PORT:-6533}:6333`.
Redis is launched with `--requirepass`, `--protected-mode yes`,
`--appendonly yes`, `--appendfsync everysec`, `--maxmemory 1gb`, and
`--maxmemory-policy noeviction` (`compose/redis.yml:25-42`); Qdrant requires
`QDRANT__SERVICE__API_KEY` and disables telemetry
(`compose/qdrant.yml:22-23`). Both services use `restart: unless-stopped`
(`redis.yml:45`, implicit via compose default for qdrant) and persist to
named volumes (`kaine-redis-data`, `kaine-qdrant-data`) rather than bind
mounts of host paths. Both compose files use the `?` substitution sigil
(`KAINE_REDIS_PASSWORD:?...`, `KAINE_QDRANT_API_KEY:?...`) which causes
`docker compose up` to abort if the secret is unset. Residual risk: telemetry
disable is set in qdrant but the redis image's own outbound calls (none in
default config) are not blocked at the network namespace level; for v1 this
is acceptable on a trusted host. Operator responsibility: in production, rename
or disable dangerous Redis commands (`FLUSHALL`, `FLUSHDB`, `CONFIG`) as
documented in row 6 of `kaine/bus/AUDIT.md`.

### 4. State at rest — APPLICATION-LAYER ENCRYPTION AVAILABLE (v1.1)

KAINE writes state to `state/` and to the named Docker volumes
`kaine-redis-data` and `kaine-qdrant-data`. As of v1.1 (the `state-encryption`
change) KAINE provides **opt-in application-layer AES-256-GCM
encryption-at-rest** for the cognitive-state files most exposed to
exfiltration. It ships **disabled** (`[security.state_encryption].enabled =
false`); enabling it is an operator decision that requires a key (see the
Operator Responsibilities and the key-management notes below). The remaining
files are still protected only by filesystem permissions and OS-layer
encryption (operator responsibility).

The runtime continues to rely on filesystem permissions for everything else:
`scripts/redis-bootstrap.sh` and `scripts/qdrant-bootstrap.sh` both `chmod
600` the generated `compose/.env` and `config/secrets.toml`
(`redis-bootstrap.sh:65, 73`; `qdrant-bootstrap.sh:56, 70`) and
`kaine/bus/config.py:73-80` warns at startup when `config/secrets.toml` is
group- or world-readable.

**Full v4 at-rest state-file inventory** (every persisted cognitive-state
artifact and its protection posture under this change):

| State file / store | Contents | Protection posture |
| --- | --- | --- |
| `state/eidolon/self_model.json` | Name, derived values/norms, identity-history, per-utterance voice features (no raw text) | **App-layer AES-256-GCM** when enabled (`kaine/modules/eidolon/document.py`); else plaintext + OS-layer |
| `state/forks/<id>/snapshot.json` | Fork/merge bundle: every module's serialized numeric state + adapter paths | **App-layer AES-256-GCM** when enabled (`kaine/lifecycle/snapshot.py`); key MUST be moved out-of-band for cross-host transfer |
| `state/evaluation/observers/**/*.jsonl` | Sidecar observer logs: PLV time series, replay association logs, welfare event counts, Nous policy logs, prediction-error/fatigue series | **App-layer AES-256-GCM** per-line when enabled (`kaine/evaluation/sink.py`); else plaintext + OS-layer |
| `state/phantasia/` (DreamerV3 checkpoints / latent states) | World-model weights + latent-state checkpoints | **App-layer AES-256-GCM-ready** (`kaine/modules/phantasia/checkpoint.py`). NOTE: the shipped `fake` backend and the current DreamerV3 adapter write NOTHING to disk (zero-persistence, in-memory only); the helper exists so any future checkpoint hook is encrypted by construction |
| Mnemos Qdrant collection (`kaine-qdrant-data` volume) | Memory embeddings + payloads | Transport-layer: Qdrant TLS + API key (see below). App-layer field encryption deferred to a future version |
| Empatheia Qdrant collection (`kaine-qdrant-data` volume) | Agent-model embeddings, predicted-behavior vectors | Transport-layer: Qdrant TLS + API key (see below). App-layer field encryption deferred |
| `state/praxis/audit.log`, `state/praxis/files/` | Praxis action audit + written files | OS-layer (operator responsibility) |
| `state/lingua/intent_expression.jsonl` | Intent/expression pairs for voice alignment — **HIGH SENSITIVITY**: embeds the assembled LLM prompt (user/bystander utterances) and the entity's raw generated text including internal monologue | OS-layer (operator responsibility) |
| `state/hypnos/adapters/` | Voice-alignment LoRA adapters | OS-layer (operator responsibility) |
| `state/vox/` | Retained TTS output | OS-layer (operator responsibility); live A/V is perception, not recording |
| `kaine-redis-data` volume | Bus AOF | OS-layer (operator responsibility); bus is loopback |

**Crypto details.** AES-256-GCM (256-bit key, fresh 96-bit `os.urandom`
nonce per message — never reused — and a 128-bit authentication tag). The
on-disk envelope is `KAINEgcm1:` magic ‖ nonce ‖ ciphertext+tag, base64-encoded
so it is UTF-8/JSON-safe. Decryption is authenticated: tampering with the
ciphertext, nonce, or tag fails with `InvalidTag` rather than returning
corrupted plaintext. A reader transparently passes through legacy plaintext
(pre-encryption files), and a disabled deployment never imports the
`cryptography` library. Implementation: `kaine/security/crypto.py`.

**Qdrant transport-layer control (Mnemos + Empatheia).** The two Qdrant
collections are not field-encrypted at the application layer in v1.1; the
transport-layer control is Qdrant TLS plus the API key generated by
`scripts/qdrant-bootstrap.sh` (`chmod 600` on `config/secrets.toml`). Per-field
or per-payload encryption of Qdrant data is deferred (see Out-of-Scope §1).

Residual risk: with encryption disabled (the default), anyone with read access
to the user's home directory can read self-model identity history, fork
bundles, sidecar logs, raw memories (Mnemos/Empatheia Qdrant volume), recorded
intent-expression pairs, and the praxis audit log. With encryption enabled,
the self-model, fork bundles, and sidecar logs are protected at rest, but the
Qdrant collections, praxis audit/files, intent-expression log, adapters, and
audio-out still require OS-layer encryption. Operator responsibility: encrypt
the home directory or KAINE working tree at the OS layer (LUKS, FileVault,
eCryptfs) for any backup-exposed or multi-user host, in addition to enabling
application-layer encryption.

**`intent_expression.jsonl` sensitivity note:** This file is HIGH sensitivity.
Each record embeds the full assembled LLM prompt (which includes user/bystander
utterances captured by the microphone) and the entity's complete generated
response including its internal monologue (chain-of-thought). It is NOT merely
"intent/expression pairs" — it is verbatim third-party personal data and entity
inner-life content in the same file. Treat it with the same care as Mnemos
memories.

**`replay_redact_content = false` consequence:** When
`[evaluation.observers].replay_redact_content` is set to `false` (the default
is `true`), the replay observer writes verbatim memory text to the replay log
under `data/evaluation/`. This converts a normally-safe sidecar log into a
transcript of the entity's episodic memory content. Keep `replay_redact_content
= true` (the shipped default) unless you have an explicit reason to override it
and understand the privacy implications.

### 5. Nexus auth posture and privacy boundary — OPERATOR-RESPONSIBLE

The Nexus FastAPI app exposes a unified console and diagnostics surface and
binds by default to `127.0.0.1:8088` (`config/kaine.toml:247-249`,
`kaine/nexus/config.py:12-13`). It has no auth: a grep of `kaine/nexus/*.py`
for `auth`, `password`, `api_key` returns no matches; `kaine/nexus/app.py`
mounts routers directly with no middleware. The defense-in-depth control is
the loopback bind plus the privacy boundary in `kaine/privacy_filter.py`
(re-exported for backward compatibility by `kaine/nexus/privacy.py`):
`PrivacyFilter.filter_for_diagnostics` removes a fixed set of content-bearing
fields (`text`, `body`, `content`, `internal_speech`, `belief_text`,
`memory_text`, `affect_reason`, `narsese`, `transcription` — see
`kaine/privacy_filter.py`) unless `dev_content_override=True`. That flag
defaults to `False` in `config/kaine.toml:260` and `kaine/nexus/config.py:19`,
and when enabled the UI shows a "dev mode" banner. The console route
(`build_conversation_router`, `kaine/nexus/conversation.py`) exposes only a
unified `GET /` that reuses the same filtered `build_diagnostics_context` as
`/diagnostics`; there is no unfiltered event stream. Residual risk: any local
process on the host can fetch diagnostics over loopback without credentials.
Operator responsibility: do not bind Nexus to a non-loopback interface in v1,
do not flip `dev_content_override` on a shared machine, and add a reverse
proxy with mutual TLS or HTTP basic auth if remote access is required.

### 6. External network calls in runtime — HARDENED

A repo-wide grep for `https://`, `urllib`, `requests.`, `huggingface`,
`hf_hub_download`, `snapshot_download` finds no runtime calls to external
networks (only documentation links in `kaine/modules/lingua/ABLITERATION.md`).
The four HTTP clients in the runtime — `kaine/modules/lingua/client.py`
(the served chat organ), `kaine/modules/audition/stt_client.py` (Speaches STT),
`kaine/modules/vox/client.py` (Chatterbox TTS), and
`kaine/modules/vox/module.py` — all default to loopback URLs
(`http://127.0.0.1:11434`, `:8000`, `:8883`). The Redis bus URL likewise
defaults to `127.0.0.1` (`kaine/bus/config.py:19`, `kaine/bus/config.py:96`).

**Single opt-in, operator-initiated exception:** `python -m kaine.research
--send` allows the operator to transmit a numeric-metrics-only research bundle.
This is the ONE explicit exception to "all-local at runtime." It is shipped
disabled (`[research_submission].enabled = false`), never automatic, requires
an interactive confirmation before any network call, and carries no entity
content (CAL 4.3). See `docs/research-participation.md`.

**Privacy hardening (this version):**
- `kaine/modules/topos/encoder.py` now sets `HF_HUB_DISABLE_TELEMETRY=1`
  before any `from_pretrained` call (matching `kaine/modules/mnemos/embeddings.py`).
- `kaine/modules/hypnos/hot_swap.py` now rejects a non-loopback
  `reload_endpoint_url` unless `KAINE_ALLOW_NONLOCAL_HOT_SWAP=1` is set.

Residual risk: `kaine/modules/topos/encoder.py` calls
`AutoImageProcessor.from_pretrained` / `AutoModel.from_pretrained`, and
`kaine/modules/mnemos/embeddings.py` instantiates `SentenceTransformer`.
These will hit `huggingface.co` on first run if the model is not in the local
HuggingFace cache (telemetry is suppressed via `HF_HUB_DISABLE_TELEMETRY=1`).
After the cache is populated they run offline. This is expected setup-time
behavior (documented in `SETUP.md` first-boot checklist) and the runtime audit
treats it as out-of-band of normal operation.

## Operator Responsibilities

These are not enforced in code; they are the operator's contract for a v1
deployment:

- **Encrypt the host or working tree at the OS layer.** Even with
  `[security.state_encryption]` enabled, KAINE does not encrypt the Qdrant
  collections (Mnemos/Empatheia), the Redis AOF, the praxis audit/files, the
  intent-expression log, the voice adapters, or audio-out. Use LUKS,
  FileVault, or equivalent for any backup-exposed or multi-user host.
- **Manage the state-encryption key (when `[security.state_encryption].enabled
  = true`).** KAINE loads a 32-byte AES-256 key from the env var named by
  `key_env_var` (default `KAINE_STATE_KEY`; supply 32 raw bytes, or base64/hex
  of 32 bytes), falling back to the Linux kernel keyring (`kaine:state_key` in
  the user keyring). With encryption enabled the entity **refuses to boot**
  without a key (fail-closed). The key is NEVER logged, hardcoded, or
  committed. The operator owns:
    - **Key generation and storage.** Generate with e.g.
      `openssl rand -base64 32`; store it outside the repo (a secrets manager,
      the kernel keyring, or an env file that is `chmod 600` and gitignored).
      Never place it in `config/kaine.toml` or any committed file.
    - **Key backup.** If the key is lost, all encrypted state
      (`state/eidolon/self_model.json`, `state/forks/`, sidecar JSONL,
      Phantasia checkpoints) is unrecoverable. Back the key up out-of-band.
    - **Key rotation.** Rotation is operator-driven: decrypt with the old key,
      re-encrypt with the new key, then update the env var/keyring. There is no
      automatic in-place re-key in v1.1.
    - **Out-of-band key transfer for cross-host fork/merge.** A fork bundle
      under `state/forks/` is encrypted with this host's key. To import it on
      another host, the SAME key must be transferred out-of-band (not alongside
      the bundle); the import fails authentication (`InvalidTag`) under a
      different key.
- **Keep the Nexus port on loopback.** `config/kaine.toml` defaults to
  `127.0.0.1:8088`. Do not change `nexus.host` to `0.0.0.0` without
  fronting Nexus with auth (reverse proxy + basic/MTLS).
- **Keep `dev_content_override = false` in production.** The privacy
  boundary only works when the override is off.
- **Do not commit `config/secrets.toml` or `compose/.env`.** The
  `.gitignore` covers these (lines: `secrets/`, `config/secrets.toml`,
  `config/secrets.*.toml`, `compose/.env`, `compose/*.env`), but the
  operator is responsible for not bypassing it (`git add -f`, alternate
  branches, etc.). Bootstrap scripts always chmod 600 these files.
- **Inspect every Praxis whitelist entry before enabling it.** Entries
  ship empty. A loose regex like `.*` makes the whitelist useless; the
  recommended posture from `kaine/modules/praxis/AUDIT.md` is alphanumeric +
  hyphen + dot + underscore patterns.
- **Rename/disable dangerous Redis commands** (`FLUSHALL`, `FLUSHDB`,
  `CONFIG`) in any deployment beyond a trusted single-user box. The audit
  treats `CONFIG GET` failures as warnings and falls back to operator
  verification.
- **Rotate the Redis password and Qdrant API key** on host migration. The
  bootstrap scripts default to rotating on every invocation; pass
  `--keep-password` / `--keep-key` only when intentional.
- **Populate the HuggingFace model cache before disconnecting from the
  network**, or pin model files via `HF_HOME` to a known offline path. The
  first run of Topos and Mnemos otherwise hits `huggingface.co`.

## Out-of-Scope (Deferred)

The following items are intentionally not addressed in v1. They are
documented here so they are not lost:

1. **Application-level encryption at rest — PARTIALLY DELIVERED in v1.1.**
   The `state-encryption` change adds opt-in AES-256-GCM encryption for
   `state/eidolon/self_model.json`, fork/merge bundles under `state/forks/`,
   sidecar observer JSONL under `state/evaluation/observers/`, and a
   checkpoint helper for `state/phantasia/` (see Finding 4). Still deferred:
   per-field/per-payload encryption of the Mnemos and Empatheia Qdrant
   collections (transport-layer Qdrant TLS + API key is the current control),
   and of the praxis audit log, intent-expression log, voice adapters, and
   audio-out. A hardware-token or kernel-keyring-backed key escrow beyond the
   current env-var/keyring loader is also future work.
2. **Nexus authentication.** Adding HTTP basic, session cookies, or mTLS
   to the Nexus surfaces. The v1 stance is "loopback is the perimeter";
   v1.1+ will add auth when multi-host or shared-host deployments are
   spec'd.
3. **Mutual-backup mesh auth.** The paper §5.2 mentions cross-host
   KAINE-to-KAINE bus mirroring. That requires Redis ACLs or per-peer
   TLS with verified client certs. Out of scope for v1.
4. **Plugin / untrusted code sandboxing.** Praxis assumes the operator
   controls all module code. v1 does not have a sandbox for third-party
   modules.
5. **Disabling dangerous Redis commands by default in `compose/redis.yml`.**
   Documented in `kaine/bus/AUDIT.md` row 6 as a recommended hardening
   step; not the compose-file default because it makes operator
   diagnostics (`CONFIG GET`) harder during early debugging.
6. **Outbound network egress filtering at the host level.** A
   network-namespace block or `iptables` egress policy would catch any
   accidental future external call. v1 relies on code review and the
   loopback defaults documented in finding 6.
7. **Binary file write effector.** Praxis v1 is text-only
   (`FileWriteRequest.content: str` in `effectors.py:25`). Binary writes
   would need an additional MIME/extension allowlist.

## Verdict

KAINE v1's security posture is appropriate for its stated threat model: a
trusted operator on a single host. The bus refuses unauthenticated Redis on
any host, the action surface (Praxis) ships locked-down, all runtime network
calls default to loopback, and the privacy boundary scrubs content from the
diagnostics surface by default. As of v1.1, opt-in AES-256-GCM
application-layer encryption-at-rest protects the self-model, fork bundles,
and sidecar logs (Finding 4). The two material residual risks — encryption of
the Qdrant collections and remaining `state/` files (still OS-layer operator
responsibility, and app-layer encryption is off by default), and no auth on
the Nexus surfaces — are explicit operator responsibilities and are tracked
above for future versions.

## 7. Live perception (microphone and camera)

KAINE ships eyes and ears, off by default. When `[audition].capture_enabled`
and/or `[topos].capture_enabled` are true, `kaine.modules.audition.live.
LiveMicrophone` opens `sounddevice.InputStream` and/or `kaine.modules.topos.
live.LiveCamera` opens `cv2.VideoCapture(device)`. Both are transducers:
raw PCM and raw frames live in process memory only, get wrapped (WAV via
`wave.open(io.BytesIO(), 'wb')` — never a file path) and handed to the
existing `process_audio`/`process_frame` entry points, then released.

The zero-persistence invariant is enforced in code and verified by
`tests/test_zero_persistence_invariant.py`:

  - No `.wav`, `.pcm`, `.raw`, `.png`, `.jpg`, `.mp4`, `.webm` (etc.)
    files appear on disk while either stream is active.
  - `git grep wave.open kaine/modules/audition/` matches only `io.BytesIO`
    arguments.
  - `git grep -E "cv2\.(imwrite|VideoWriter)" kaine/` returns empty.

The only things that persist are: (1) the brain's *processed* perceptions
(transcribed text + frame embeddings) which flow through the bus and Mnemos
as memory — same as before; (2) `state/perception/runtime.json` and
`desired.json`, which contain only booleans and ISO timestamps (no
sensory content); (3) standard logger lines for capture state transitions
(`capture_started`, `capture_stopped`, `utterance_started`,
`utterance_ended`, `frame_capture_failed`) — never transcribed text.

The Nexus on-air banner ("🔴 microphone on" / "🔴 camera on") is rendered
on both the console (`/`) and the diagnostics page
(`/diagnostics`) whenever `state/perception/runtime.json` reports a stream
active. Operators toggle on/off at runtime via `POST /diagnostics/
perception/toggle`, which writes only the desired-state file; the perception
tasks poll it within ~250 ms and start/stop themselves.

**Operator responsibility:** in shared physical spaces (homes, offices),
the hardware kill switch (unplugging the microphone, covering the camera)
remains the strongest guarantee. KAINE's banner tells you when the stream
is open; it does not substitute for physical control. If you deploy KAINE
on a host where other people speak or move in front of the device, get
their consent before enabling either stream.

## 8. Voice-alignment training (Hypnos sleep cycle)

Hypnos can train a LoRA adapter on top of the base model during sleep
cycles to nudge Lingua toward the entity's own voice. The pipeline is
**off by default** behind a two-layer gate
(`[hypnos.voice_alignment].enabled = true` AND env var
`KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`) and never modifies the
base model weights — every accepted adapter lands as a new directory
under `[hypnos.voice_alignment].adapter_output_dir`.

The trainer enforces a **capability-loss veto**: it scores the model
on a probe set both before and after the DPO step, and rejects the
adapter (removing the tmp directory) if capability drops by more than
`capability_loss_threshold` (default `0.05`). The default probe set is
small and generic (`kaine/modules/hypnos/eval_probes/default.jsonl`);
operators with a domain-specific deployment should substitute their
own via `[hypnos.voice_alignment].capability_probe_path`.

Adapter promotion is atomic (`os.replace` of a `.tmp` directory plus
a temp-symlink + replace for the `current` pointer), so concurrent
readers never see a partial state. Retention keeps the last N
accepted adapters (default 5); the `current` target is never evicted.

**Rollback procedure** when a deployed adapter misbehaves:
1. Stop KAINE (or pause Lingua).
2. `rm -rf <adapter_output_dir>/<bad-timestamp>/` and re-point the
   `current` symlink at the previous accepted adapter.
3. Reload Lingua's backing service.
4. Restart KAINE.

The base model at `[hypnos.voice_alignment].base_model_path` is never
modified by this pipeline. See `kaine/modules/hypnos/VOICE_ALIGNMENT.md`
for the full procedure, the three hot-swap modes, and the operator-
responsibility checklist.
