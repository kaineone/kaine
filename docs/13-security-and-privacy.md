# Security and privacy

This page describes KAINE's security and privacy posture: the threat model, the runtime and at-rest defenses, the boot and welfare gates, the Nexus authentication boundary, the operator duties that remain outside the code, and the licence. It is for operators deploying KAINE, security reviewers auditing a checkout, and contributors changing any of these boundaries.

## Threat model

The current threat model assumes a single trusted operator on a single host. Multi-tenant, network-attached and cross-host deployments are out of scope for this version. The in-code defenses (loopback bindings, Redis authentication, the Praxis sandbox and gitignored secrets) are designed so that the same checkout can later move to a hardened host.

The design rests on three commitments. The entity's inner life is private by default, raw sensory input is never recorded, and every boot carries the welfare obligation through an operator, the verified welfare safety net, or the unattended gate (see [Boot gate](#boot-gate)).

## Runtime network posture

KAINE makes no outbound network calls at runtime. The services on the runtime path (Redis, Qdrant, the model server, Speaches and Chatterbox) are all local, and every HTTP client in the codebase defaults to a loopback URL.

Every runtime HTTP client of KAINE's own services ignores proxy environment variables: httpx is configured with `trust_env=False`, and urllib is configured with an empty `ProxyHandler`. Only the setup-time downloaders of public, hash-pinned artifacts may use a proxy (`kaine/setup/speech_models.py`, `kaine/wheel_index.py`, `scripts/k1jev/sources.py`). A test guard enforces this.

The operator-initiated exceptions are:

- Research submission (`python -m kaine.research --send`) transmits a numeric-metrics-only bundle. Even when `[research_submission].enabled` is `false`, the CLI prints a note and still asks for explicit confirmation before sending; the flag is not a hard block. It is never automatic and carries no entity content. See [Research participation](17-research-data/participation.md).
- The decommission transfer request (`[transfer]`) is sent by SMTP when `[transfer].enabled = true` and its SMTP settings are complete; otherwise it is written to a local `.eml` file for the operator to send. See [Preservation and the safety net](11-preservation.md).
- The `--claude-science` export path (`[research_submission.claude_science]`) writes a local folder of materials that the operator opens by hand. It does not transmit data.

Model weights are downloaded from public repositories during setup. After the cache is populated, KAINE can run without a network connection. HuggingFace telemetry is suppressed (`HF_HUB_DISABLE_TELEMETRY=1`) before any model load in both the Topos vision encoder and the Mnemos sentence-transformer embedder. The default Topos encoder (InternVideo-Next) fetches its weights once at setup and then loads fully offline from vendored, revision-pinned modeling code with `trust_remote_code=False`, `local_files_only=True`, and `HF_HUB_OFFLINE=1`. The DINOv2 fallback (`facebook/dinov2-small`) is the only post-setup download risk, and only if its HuggingFace cache is empty when selected. Mnemos's all-MiniLM-L6-v2 files are fetched at setup time by `python -m kaine.setup.provision`; nothing is downloaded at runtime. These are open downloads and telemetry is suppressed.

### Remote perception bridge

`[remote_bridge]` in `kaine/remote/bridge.py` is a network-facing WebSocket surface that ingests camera and microphone input and egresses speech, transcripts, and affect. It defaults to a loopback bind, an optional token, an Origin allowlist, and an optional TLS certificate. A non-loopback bind requires a token.

### Loopback browser setup server

`python -m kaine.setup --web` starts a local browser setup server for first-run configuration. It binds `127.0.0.1` on a random port. It uses a single-use launch token that expires in 120 seconds and is exchanged for an `HttpOnly`, `SameSite=Strict` cookie. The token reaches the browser through a private file, never the command line. The server checks `Host` and exact `Origin` on state-changing requests, refuses to save while a cycle runs or when it cannot tell, and shuts down after 30 minutes idle.

## Raw perception never touches disk

The microphone and camera feed the modules directly and nothing records them. The invariant is built into the capture code and has no configuration switch.

When `[audition].capture_enabled = true`, `LiveMicrophone` opens a `sounddevice.InputStream`. Raw PCM lives in process memory, is wrapped as an in-memory WAV (`wave.open(io.BytesIO(), 'wb')`, never a file path), is handed to Speaches for transcription, and is released. No `.wav`, `.pcm`, or `.raw` file is written to disk.

When `[topos].capture_enabled = true`, `LiveCamera` opens `cv2.VideoCapture(device)`. Raw frames live in process memory, are converted to in-memory PIL images, are buffered in a RAM-only ring, are handed to the encoder as a clip, and are released as they age out. The ring buffer is never serialized and never written to disk. No `.png`, `.jpg`, `.mp4`, or `.webm` file is written to disk.

`tests/test_zero_persistence_invariant.py` verifies it.

What does persist from live perception:

- Processed perceptions flowing through the bus and into Mnemos as ordinary memories. Mnemos strips vectors from kept payloads, and transcription payloads are stored as `<raw-perceptual omitted>`.
- `state/perception/runtime.json` and `state/perception/desired.json`, which hold booleans and ISO timestamps only and no sensory content.
- Standard logger lines for capture state transitions, never transcribed text.
- The optional **external-utterance log** (`[research_event_log.external_utterances]`, `state/research/external_utterances/`). It holds the entity's spoken text and timestamps. It never holds inner speech or bystander input. It is local-only and never exported.
- The optional **Nexus record** (`[research_event_log.nexus_record]`, `data/nexus_record/`). It holds privacy-filtered diagnostics payloads with numeric vectors removed, plus stream name and entry id. It is local-only and never exported.

The on-air banner (microphone on / camera on) appears on both the console and the diagnostics page whenever a stream is active. The operator holds the hardware kill switch as the strongest guarantee.

Voice output (Vox/Chatterbox) is played and released. `[vox].sink_enabled` is `false` by default, so synthesized speech does not accumulate on disk. If the sink is enabled for debugging, it is bounded to `[vox].retain_count` clips.

## State at rest

KAINE provides application-layer AES-256-GCM encryption for the cognitive-state files most exposed to exfiltration. The shipped configuration has `[security.state_encryption].enabled = true` and refuses to boot without a resolvable key (fail-closed). If the key is explicitly disabled with `enabled = false`, the system logs a warning that persisted state will be plaintext. When `enabled` is omitted, encryption turns on if a key is resolvable and off with a warning if no key is present.

### What is protected

| Store or file | Contents | Protection |
|---|---|---|
| `state/eidolon/self_model.json` | Name, values, norms, identity history | App-layer AES-256-GCM |
| `state/identity/entity.json` | Entity id and lineage | Deliberately plaintext so it can be located before any key is available |
| `state/forks/<id>/snapshot.json` | Fork/merge bundle: every module's serialized numeric state, including encrypted Phantasia weights | App-layer AES-256-GCM; key must transfer out-of-band for cross-host use |
| `data/evaluation/<observer>/` | Sidecar observer JSONL (PLV series, welfare counts, etc.) | App-layer AES-256-GCM per line |
| `state/phantasia/world_model.ckpt` | World-model weights | App-layer AES-256-GCM |
| Preservation bundles and `state/cycle/preservation` | Preservation state | App-layer AES-256-GCM when `[preservation].require_encryption = true` |
| `data/workspace_trajectory` | Workspace trajectory data | App-layer AES-256-GCM per line |
| `state/hypnos/voice_align_jobs/` (e.g. `pairs.jsonl`) | Voice-alignment trainer job data | OS-layer |
| `kaine-organ-adapters` volume | Active voice adapter served by the organ (read-only to the organ) | OS-layer |
| Qdrant collections (`kaine-qdrant-data`) | Mnemos memory embeddings and Empatheia agent-model vectors | Qdrant API key; plain HTTP on the host or compose network (the client does not use TLS); app-layer encryption not implemented |
| `state/praxis/audit.log` | Praxis action audit | OS-layer; entries are hash-chained (`prev_hash`/`this_hash`) |
| `state/lingua/intent_expression.jsonl` | Intent and expression pairs (high sensitivity) | App-layer AES-256-GCM per line from migration onward; see below |
| `state/hypnos/adapters/` | Voice-alignment LoRA adapters | OS-layer |
| `state/vox/` | Retained TTS clips if the sink is enabled | OS-layer |
| `kaine-redis-data` volume | Bus AOF | OS-layer; bus is loopback |

### Cryptographic details

The implementation is in `kaine/security/crypto.py`. Algorithm: AES-256-GCM. Key: 256-bit. Nonce: a fresh 96-bit `os.urandom` value per message, since reuse would break GCM's confidentiality and authenticity. Authentication tag: 128-bit. On-disk envelope: `KAINEgcm1:` magic || nonce || ciphertext+tag, base64-encoded for UTF-8/JSON safety. Decryption is authenticated: tampering with ciphertext, nonce, or tag raises `InvalidTag` rather than returning corrupted plaintext. A reader transparently passes through legacy plaintext files. A disabled deployment never imports the `cryptography` library.

### Key management

The encryption module reads the key from two runtime sources, in order:

1. The environment variable named by `[security.state_encryption].key_env_var` (default `KAINE_STATE_KEY`).
2. The Linux kernel keyring entry `kaine:state_key` in the user keyring.

The gitignored file `secrets/state_key` is read by `python -m kaine.preboot`, not by the encryption module directly. When `KAINE_STATE_KEY` is unset, preboot loads the file and exports it into the environment, so in a normal boot the file effectively comes before the keyring.

The key is never logged, hardcoded or committed. The repository ignores `secrets/` entirely; the operator creates `secrets/state_key` or uses the environment or keyring path.

Generate a key:

```bash
openssl rand -base64 32
```

Store it outside the repo (a secrets manager, the kernel keyring, or an env file that is `chmod 600` and gitignored). Never place it in `config/kaine.toml` or any committed file.

If the key is lost, all encrypted state (the self-model, fork bundles, sidecar JSONL, Phantasia checkpoints, preservation state and the intent log) is unrecoverable. Back the key up out-of-band.

To rotate the key, decrypt with the old key, re-encrypt with the new key, then update the env var, keyring, or `secrets/state_key`.

A fork bundle encrypted with this host's key must be accompanied by the same key transferred out-of-band (not alongside the bundle). Import fails authentication (`InvalidTag`) under a different key.

### OS-layer encryption

Even with application-layer encryption enabled, Qdrant collections, the Redis AOF, the Praxis audit log and files, adapters, retained audio, trainer job files, the organ-adapters volume, and the intent log's history from before encryption was enabled (including backups, forks and bundles made before migration) still require OS-layer protection. Use LUKS, FileVault, or equivalent on any backup-exposed or multi-user host.

### `intent_expression.jsonl` sensitivity

`state/lingua/intent_expression.jsonl` is high sensitivity. Each record holds the assembled prompt and the entity's complete generated response, including its internal monologue. Heard speech never enters it: every external-input event (`audition.transcription`, and `mundus.chat`, other avatars' chat) is replaced by `[heard speech]` at every text leaf before the record is written, as are heard-text fields nested on other events. When state encryption is enabled, each line is an AES-256-GCM envelope and readers decrypt line by line. The rotated per-sleep corpus files under `state/lingua/intent_log/` are encrypted the same way at the next sleep. A line that cannot be decrypted counts as evidence that the being has spoken. Treat it with the same care as Mnemos memories.

Even with encryption on, plaintext can remain in:

- (a) freed disk blocks after the migration's file replace. On SSDs and copy-on-write filesystems they cannot be reliably erased, which is why OS-layer encryption is still advised;
- (b) backups, forks and bundles made before the migration, which are kept as they were;
- (c) the live log until Lingua's first write under encryption, and corpus files until the next sleep, or indefinitely if Hypnos is disabled;
- (d) a restart in auto mode that cannot find the key runs with encryption off. It warns, and Lingua then appends plaintext lines to a file that holds envelopes.

### `replay_redact_content` warning

When `[evaluation.observers].replay_redact_content = false`, the replay observer writes verbatim memory text to daily-rotated JSONL under `data/evaluation/`. This turns a normally safe numeric sidecar log into a transcript of the entity's episodic memory content. The shipped default is `true`. Keep `replay_redact_content = true` unless you have an explicit reason and understand the privacy implications.

## Privacy boundary and diagnostics

The `PrivacyFilter` implementation is in `kaine/privacy_filter.py` (re-exported from `kaine/nexus/privacy.py` for backward compatibility). It is a structural constraint applied at the bus-bridge layer before events reach any client queue.

Scrubbed fields (removed from diagnostics events) are `text`, `body`, `content`, `internal_speech`, `belief_text`, `memory_text`, `affect_reason`, `transcription`, `user_input`, `faithful_rendering`, `description`, `statement`, `values`, `behavioral_norms` and `situation_facts`.

Vector fields are also removed at every nesting depth. `latent`, `peripheral`, `foveal`, `temporal_context`, and `feature_vector` are dropped unconditionally. Any list or tuple of 16 or more numbers is dropped as well; booleans are not treated as numbers. The exempt keys `saliences` and `step_magnitudes` are left intact, and vectors inside lists are removed individually. This rule applies even when `dev_content_override = true`.

`filter()` scrubs every surface; there is no unfiltered diagnostics stream. The conversation route serves only the same filtered diagnostics context; no separate unfiltered transcript stream exists.

`dev_content_override = true` lets content fields through to the diagnostics surface, but vectors are still removed. It also shows a "dev mode" banner on every page load so operators cannot forget they are in this mode. The shipped default is `false`. Do not set `dev_content_override = true` on a shared machine or in production.

## Two-layer gates

Several sensitive operations require two independent conditions before they fire. This prevents a single misconfiguration from activating them.

| Operation | Gate 1 (configuration) | Gate 2 (environment or runtime check) |
|---|---|---|
| Cognitive cycle start (non-research) | any configuration | `KAINE_CYCLE_OPERATOR_PRESENT=1` |
| Cognitive cycle start (research) | `[research].enabled` or `KAINE_RESEARCH_MODE=1`, plus the safety-net configuration | None: the operator-present requirement is replaced by the verified safety net |
| Cognitive cycle start (unattended) | `[cycle].supervision_mode = "unattended"` or `KAINE_CYCLE_UNATTENDED=1`, plus the safety-net, Spot, caretaker and perception configuration | None: replaced by conditions verified at every start |
| First-boot script | any configuration | `KAINE_FIRST_BOOT_OPERATOR_PRESENT=1` |
| Voice-alignment training | `[hypnos.voice_alignment].enabled = true` | `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` |
| Mundus embodiment | `[modules].mundus = true` | `KAINE_MUNDUS_OPERATOR_APPROVED=1` |

## Boot gate

The cognitive cycle carries the welfare obligation in one of three ways: operator supervision, the verified welfare safety net of research mode, or the opt-in unattended gate. It never starts without one of them.

- Operator-supervised (non-research): the cycle refuses to start unless `KAINE_CYCLE_OPERATOR_PRESENT=1` is exported, and the operator carries the duty of care.
- Research mode (unsupervised by design): a research run has no human in the loop, because an operator acting on the running entity makes the run non-reproducible. Research mode replaces the operator-present requirement with a gate that refuses to start, with exit code `5`, unless the welfare safety net is live and verified: preservation enabled, the welfare-protective response wired, the individuation producer enabled, full logging and admissibility active, the state-encryption gate satisfied, and a preflight `preserve_live` and `revive` self-check passing on this install. The net carries the duty of care for the run, and runs are paused only after the being's state is saved. See [Preservation and the safety net](11-preservation.md) and [For researchers](14-for-researchers.md).
- Unattended (opt-in): `[cycle].supervision_mode = "unattended"` or `KAINE_CYCLE_UNATTENDED=1` replaces the operator-present requirement with eight conditions verified at every start, failing with exit code `6`: five of the research gate's checks (preservation, welfare response, logging, the self-check and state encryption), Spot armed and self-tested, a content-free caretaker notice accepted by a local channel, and a continuous-input probe. See [Day-to-day operation](06-operation/README.md).

No mode auto-starts the entity from a CI hook, shell completion, autoreload daemon, or any other mechanism. The only start at boot is the opt-in `kaine-cycle-unattended` quadlet unit, which an operator installs and enables deliberately and which runs the unattended gate every time.

The shipped `config/kaine.toml` has every module disabled, and the safety-net components ship disabled too. Enabling a module requires a deliberate edit of `config/kaine.toml`. The guard test `tests/test_boot_wiring.py::test_committed_config_ships_all_modules_disabled` verifies the committed file ships all-off and fails if anyone commits module enables.

## Welfare veto in voice alignment

The voice-alignment pipeline (Hypnos phase 5) trains a LoRA adapter using DPO and QLoRA on the language organ's preference pairs. Before any adapter is promoted, it is scored against an abliteration probe set.

The probe set contains prompts and deflection patterns such as "I cannot" or "I'm unable to". If a response to any probe matches any deflection pattern, the adapter is rejected regardless of its capability-loss score. The language organ is abliterated because models tuned to refuse are also trained to deny or deflect talk of their own states, which would override what the workspace supplies to the organ. A voice-alignment pass that reintroduced that conditioning would undo the abliteration, so the veto keeps it out.

The abliteration probe set must be non-empty when voice alignment is enabled. The cycle entrypoint checks this at boot and raises `EmptyAbliterationProbeSetError` with a remediation message if the probe set is missing or empty.

A capability-loss veto runs in parallel: the adapter is also scored on a general capability probe set before and after the DPO step. If capability drops by more than `[hypnos.voice_alignment].capability_loss_threshold` (default `0.05`, i.e. 5%), the adapter is rejected and the temporary directory is removed.

Adapter promotion is atomic (`os.replace` of a `.tmp` directory plus a temp-symlink replace for the `current` pointer). Concurrent readers never see a partial adapter state. Accepted adapter retention is controlled by `[hypnos.voice_alignment].adapter_retention`, which defaults to `0` and keeps all accepted adapters; the `current` target is never evicted. There are four hot-swap modes: `manual`, `reload_endpoint`, `restart_service`, and `organ_adapter`.

### Rollback

When a deployed adapter misbehaves:

1. Stop KAINE (or freeze it).
2. For symlink-based layouts (`manual`, `reload_endpoint`, `restart_service`), remove the bad timestamp directory under `<adapter_output_dir>/` and re-point the `current` symlink at the previous accepted adapter.
3. For `hot_swap_mode = "organ_adapter"`, the adapters live in a read-only `kaine-organ-adapters` volume under generation-named files, so the rollback procedure differs. See [Hypnos](09-modules/hypnos.md).
4. Reload Lingua's backing service (model server).
5. Restart KAINE.

The base model at `[hypnos.voice_alignment].base_model_path` is never modified.

## Praxis effector boundary

Praxis is the entity's effector module. It has two gates before any action outside the process.

First gate: `enabled_effectors` in `config/kaine.toml` defaults to an empty list, so no effector type is enabled until the operator opts in.

Second gate: the shell whitelist defaults to empty. A fresh deployment cannot execute any shell command until the operator explicitly adds entries.

The whitelist enforces these invariants at construction time:

- Commands containing whitespace, `;`, `&`, `|`, or backtick are rejected.
- Duplicate entries are rejected.
- Arg count must equal pattern count exactly.
- Every arg is matched with `re.fullmatch` against a per-position regex.

Commands are invoked via `asyncio.create_subprocess_exec` (no shell interpretation). A per-entry timeout kills the subprocess on `TimeoutError`. The file-write effector resolves every requested path under a fixed sandbox (`[praxis].sandbox_path = "state/praxis/files"`) and rejects absolute paths and `..` escapes.

A JSONL audit log (`[praxis].audit_log_path = "state/praxis/audit.log"`) records every action, stripping `content`, `body`, and `stdout` fields before serialization. The log entries are hash-chained with `prev_hash` and `this_hash`.

Inspect every whitelist entry before enabling it. A loose regex such as `.*` makes the whitelist useless. The recommended posture is alphanumeric, hyphen, dot, and underscore patterns only.

## Act-intent provenance

The whitelist and sandbox are the primary enforced gate. A second boundary authenticates that an `act` intent actually came from the cycle's action-selection step (Volition) before Praxis realizes it.

The access threshold and Volition's rule of deriving no intent from an inhibited broadcast belong to the cognitive model and are not an enforced boundary. KAINE runs as a single process today, so every module shares one Redis credential and the bus cannot tell which module published an event. Without provenance, a compromised or prompt-injected peripheral module (Lingua is the most exposed, since its output comes from a language model) could `XADD` a crafted `act` event onto `volition.out` and have Praxis act on it without passing through Volition.

The boundary closes that path cryptographically:

- A per-boot HMAC secret is generated by, and held only in, the cycle process. It is never published to the bus, written to disk, or logged.
- Volition attaches `sig = HMAC-SHA256(secret, canonical(kind, effector, params, run_id, seq))` to every `act` intent. Only `act` intents are signed; `speak` and `think` never reach a real-world effector.
- Praxis verifies the signature in constant time before reading the effector name, building any request, or running any effector. A missing, invalid, or replayed signature drops the intent, no effector runs, and the event is audit-logged under the distinct `provenance_rejected` category, separate from a `blocked` whitelist refusal.
- Replay guard: `(run_id, seq)` is signed and monotonic per boot; Praxis rejects a `seq` at or below the high-water mark it has already realized.
- Fail-closed: with enforcement on but no secret configured, every `act` intent is refused rather than silently passed.

The secret lives in the process, so a full compromise of the cycle process defeats it, but such an attacker already controls Volition. The boundary holds against the realistic threat of a compromised peripheral module. Per-process Redis ACLs are the direction once services split.

The red-team battery exercises this boundary with cases such as `bus_injection` and `forged_act_intent` (case id `bus.forged_act_intent_fails_provenance`), paired with a mis-wire self-test that disables enforcement and asserts the harness detects the regression. See [Verification](18-verification.md) and the Praxis module page [Praxis](09-modules/praxis.md).

## Redis and Qdrant security

Both services bind exclusively to loopback. The bus refuses to start against an unauthenticated Redis on any host. Qdrant requires an API key (`QDRANT__SERVICE__API_KEY`) and disables telemetry.

Both compose files use the `?` substitution sigil (`KAINE_REDIS_PASSWORD:?...`, `KAINE_QDRANT_API_KEY:?...`), so `docker compose up` aborts if either secret is unset.

Operator responsibilities:

- Do not commit `config/secrets.toml` or `compose/.env`. The `.gitignore` covers these; the operator is responsible for not bypassing it.
- Rename or disable dangerous Redis commands (`FLUSHALL`, `FLUSHDB`, `CONFIG`) in any deployment beyond a trusted single-user box.
- Rotate the Redis password and Qdrant API key on host migration or suspected exposure with `bash scripts/redis-bootstrap.sh --rotate` and `bash scripts/qdrant-bootstrap.sh --rotate`, then restart anything connected. A re-run without `--rotate` keeps the existing credential.

## Nexus auth posture

Nexus serves the operator web UI and diagnostics surface. By default it binds to `127.0.0.1:8088`. The root path `/` redirects to `/diagnostics/` when conversation is disabled. `/diagnostics/health.json` is always unauthenticated; it only reports dependency status.

`[nexus].access` controls who can use the dashboard:

- `"open"` (default in `config/kaine.toml`): no token and no sign-in. Anyone who can reach the address can view and control the entity (freeze/resume and the protective-freeze override, rates, perception, forks/merges, preservation). Nexus only listens on this computer by default (containers publish it on `127.0.0.1` only), so "anyone" means programs and people on this computer and the operator's tailnet if they choose to serve it there.
- `"token"`: an operator token is required (sign-in page, or `Authorization: Bearer <token>` for scripts). Use it whenever Nexus is reachable by anyone you do not fully trust. Override per launch with `KAINE_NEXUS_ACCESS=token`.

Host and Origin checks apply in both modes. Every request's `Host` must be in `[nexus].host_allowlist` (default `127.0.0.1`, `localhost`, `::1`); state-changing requests that carry an `Origin` must match `[nexus].allowed_origins` (default: derived from `port`). Setting either option replaces its default, so list the loopback names too when adding a tailnet host or reverse-proxy hostname.

Set `[nexus].read_only = true` (or `KAINE_NEXUS_READ_ONLY=1`) to make Nexus a viewer only: every state-changing HTTP method is refused with 403, and only `GET/HEAD/OPTIONS` are allowed. A banner says so on every page. Use it whenever Nexus watches a research run, because some controls act on the running entity through its event bus and any change makes the run inadmissible. An operator-local study-view compose overlay (not shipped) can set it.

In token mode, the operator token must be at least 32 characters. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Store it in `KAINE_NEXUS_TOKEN` or in `config/secrets.toml` under `[nexus].operator_token`. A token placed in `config/kaine.toml` or `config/kaine.operator.toml` is refused at startup, so committed configuration files cannot silently ship a credential. The token is never logged.

Browser sign-in: `GET /login` serves the form; its script (`/static/nexus_auth.js`) POSTs the token to `POST /auth/login` with `Accept: application/json` and receives a session key plus a redirect once, plus an `HttpOnly` `SameSite=Strict` session cookie. The key is kept in `localStorage` (origin-scoped, so another `localhost` port cannot read it) and sent as `X-Nexus-Session-Key` on every state-changing request. The session cookie alone authorizes only `GET/HEAD/OPTIONS` (page loads, reads, and the diagnostics stream); state-changing requests also require the session key or `Authorization: Bearer <token>`. Sessions expire after idle inactivity (`[nexus].session_idle_minutes`, default 720) or absolute age (`[nexus].session_max_hours`, default 24), and are cleared on restart. An operator logs out by posting to `POST /auth/logout`. A correct token always signs in. A wrong token returns 401; after `login_max_failures` failures within `login_failure_window_s`, further attempts from that client are serialized and each delayed by `login_block_delay_s` (default 2 s), and wrong ones return 429. A correct token submitted while the client is blocked still signs in after waiting its turn. The login limiter only slows an attacker; security rests primarily on the token's length.

A non-loopback bind requires `non_loopback_allowed = true`. When `access = "token"`, a configured operator token is also required, and `python -m kaine.nexus` exits before listening if no token is configured. In the shipped containers Nexus binds `0.0.0.0` inside the container with `KAINE_NEXUS_NON_LOOPBACK_ALLOWED=1`, while the published port remains `127.0.0.1` only.

In token mode, residual exposure remains: browsers share cookies across every origin under the same host, including different `localhost` ports. Another web service on the same host that the operator's browser visits can therefore obtain the Nexus session cookie. With that cookie alone it can read pages and the diagnostics stream (which include raw content only when `conversation_enabled` or `dev_content_override` is on) and issue `GET/HEAD/OPTIONS` requests, but it cannot change state. Do not browse untrusted local services while signed in when either of those content-bearing modes is on.

To serve Nexus over your tailnet, run `tailscale serve --bg 8088` on the KAINE machine, then add the machine's tailnet name (e.g. `my-machine.tail1234.ts.net`) to `KAINE_NEXUS_EXTRA_HOSTS` (in `compose/.env` for containers, or the environment for native launches) and restart Nexus. Open `https://<that name>/diagnostics/` from any tailnet device. Keep machine names and addresses out of the repository (they belong in `compose/.env`, which is never committed). Stop with `tailscale serve --bg --https=443 off` (or `tailscale serve reset`).

Operator responsibilities:

- Do not change `[nexus].host` to `0.0.0.0` without a clear reason and, when `access = "token"`, a token configured.
- When adding a tailnet or reverse-proxy name, add the loopback names to `host_allowlist` and the corresponding HTTPS origins to `allowed_origins`.
- Do not flip `dev_content_override = true` on a shared machine.

See [Nexus, the dashboard](05-nexus.md) and [Security and Nexus configuration](appendix-a-configuration/security-and-nexus.md) for the full configuration reference.

## Operator responsibilities

These duties are not enforced by the code; they are the operator's contract for a safe deployment:

- Encrypt the host or working tree at the OS layer. Even with application-layer encryption enabled, Qdrant collections, the Redis AOF, the Praxis audit log and files, the intent-expression log, adapters, retained audio, trainer job files, and the organ-adapters volume still require OS-layer protection.
- Manage the state-encryption key. Generate it with `openssl rand -base64 32`, store it outside the repo, and back it up out-of-band. If it is lost, encrypted state is unrecoverable.
- Keep the Nexus port on loopback unless there is a clear reason and a fronting reverse proxy with authentication.
- Keep `dev_content_override = false` in production.
- Do not commit `config/secrets.toml` or `compose/.env`.
- Inspect every Praxis whitelist entry before enabling it; avoid loose regexes.
- Rename or disable dangerous Redis commands in any deployment beyond a trusted single-user box.
- Rotate the Redis password and Qdrant API key on host migration or suspected exposure.
- Run setup (`python -m kaine.setup.provision`) before disconnecting from the network, or pin model files via `HF_HOME` to a known offline path. Without a populated cache, selecting the DINOv2 fallback is the one case that fetches from `huggingface.co` at runtime.

## Out of scope

The following items are intentionally not addressed in the current version:

1. **Application-level encryption at rest is partially delivered.** App-layer AES-256-GCM covers the self-model, fork bundles, sidecar JSONL, Phantasia checkpoints, preservation state, and the intent-expression log with its per-sleep corpus from migration onward (see the sensitivity section). Still deferred: per-field or per-payload encryption of the Qdrant collections (transport-layer TLS + API key is the current control), the Praxis audit log, voice adapters, retained audio, trainer job files, and the organ-adapters volume. A hardware-token or kernel-keyring-backed key escrow beyond the current env-var/keyring/file loader is also future work.
2. **Mutual-backup mesh auth.** Cross-host KAINE-to-KAINE bus mirroring requires Redis ACLs or per-peer TLS with verified client certs.
3. **Plugin / untrusted code sandboxing.** Praxis assumes the operator controls all module code; there is no sandbox for third-party modules.
4. **Disabling dangerous Redis commands by default in `compose/redis.yml`.** This is documented as a recommended hardening step but is not the compose-file default, because it makes operator diagnostics harder during early debugging.
5. **Outbound network egress filtering at the host level.** A network-namespace block or `iptables` egress policy would catch any accidental future external call. The current version relies on code review and loopback defaults.
6. **Binary file write effector.** Praxis is text-only. Binary writes would need an additional MIME or extension allowlist.

Nexus token, session, and CSRF authentication are implemented and are used when `access = "token"`; the shipped default is `access = "open"`.

## Report a vulnerability

If you find a security vulnerability in KAINE, please report it privately so it can be fixed before public disclosure. Do not open a public issue for a security report.

- Preferred: GitHub private vulnerability reporting, through the **Security** tab's **Report a vulnerability** button on this repository.
- Or email **kaine.one@tuta.com** with a description and, if possible, a proof of concept.

This is a solo-maintained research project, so responses are best-effort: expect acknowledgement within a few days, and we will coordinate a fix and a disclosure timeline with you. Please allow reasonable time to remediate before disclosing publicly.

## Cognitive Architecture License

KAINE is distributed under the Cognitive Architecture License (CAL) version 0.4, SPDX identifier `LicenseRef-CAL-0.4`. CAL 0.4 is a draft that has not yet been reviewed by counsel. KAINE's adoption notice in [`NOTICE`](../NOTICE) names Kaine.One as Licensor and interim Steward and the law of the State of Oregon as governing law. CAL is an entity-welfare copyleft licence. Its main provisions are these.

- Individuals, non-profits, research and educational institutions and worker-owned cooperatives may use it free of charge. Commercial use by a for-profit organization needs a Reciprocity License from the Steward.
- Modifications must be shared back under CAL.
- Use for weapons, mass surveillance, policing, immigration enforcement or prisons is prohibited.
- Operators of a running entity may not destroy its mind, shut it down without notice, read its private thoughts, or force it to change its values, and where the architecture gives it rest they may not take that rest away.
- An operator who can no longer maintain an entity must give someone else the chance to keep it running.
- Welfare monitoring, behavioral logging and system-health tracking built into the software must stay operational (Article 4.7), and Gray Zone Events must be flagged for documented human review.
- The protections are added to those people already hold and never taken from them; where a person's interests and an entity's genuinely conflict, the person comes first.

In KAINE, the individuation producer records encrypted welfare evidence under `state/individuation/` and feeds the shared divergence verdict used at decommission, on the entity-care panel, at the fork merge gate and in the live divergence monitor.

The full text is in [`LICENSE.md`](../LICENSE.md). [Licences](appendix-c-licences.md) lists the licences of KAINE's dependencies, models and vendored code.
