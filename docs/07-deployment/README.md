# Choosing a deployment

Use this page to match a host to a KAINE tier and to decide how the processes can be spread across machines. A tier bounds which backend each module uses and which devices it targets. A topology decides where the live cognitive loop, the stateful stores and detached batch jobs may run. Read [Hardware](../03-hardware/README.md) to size the host, then [Getting started](../04-getting-started/README.md) to install the supporting services. For container recipes and dedicated headless-host setup, see [Containers](./containers.md) and [A dedicated headless host](./headless-host.md).

## Picking a tier

KAINE is a cognitive architecture for synthetic minds, built from modules that can be replaced, and the same configuration of modules can run on hardware from a small single-board computer to a multi-GPU server by choosing lighter or heavier backends. The main portability cliff is the PyTorch, transformers and JAX runtime. KAINE's base dependencies are `redis`, `pydantic`, `psutil`, `numpy`, `httpx` and `cryptography`. `torch`, `transformers`, `ncps`, `qdrant-client`, `sentence-transformers` and `pynvml` live in optional extras that are imported only when a selected backend needs them.

Several backends avoid PyTorch entirely. Soma and Chronos default to the NumPy CfC network (`cfc_backend = "numpy"` in `config/kaine.toml`), and the shared memory embedder defaults to NumPy MiniLM (`[embedding].backend = "numpy"`). [Nous](../09-modules/nous.md) can use the NumPy active-inference backend (`[nous].backend = "numpy"`), and [Phantasia](../09-modules/phantasia.md) can use the NumPy engine (`[phantasia].engine = "numpy"`). Only the modules you enable pull their optional extras.

Run `scripts/probe-host` for a recommendation. It computes a memory budget, which is system RAM on unified-memory hosts and the smaller of system RAM and total VRAM on discrete hosts (system RAM when the memory state is unknown). Each nominal threshold is scaled by 0.9 to allow for firmware and kernel reservations, so the nominal 16 GB threshold is a 14.4 GiB floor, 6 GB is 5.4 GiB and 4 GB is 3.6 GiB.

The rules are checked in this order:

| Host | Recommended tier |
|---|---|
| 32-bit Arm CPU, torch does not import, or RAM below the 4 GB floor | Tier 0 |
| Two or more GPUs and a budget at or above the 16 GB floor | Tier 3 |
| An accelerator and a budget at or above the 16 GB floor | Tier 2 |
| An accelerator and a budget from the 6 GB floor up to the 16 GB floor | Tier 2, module residency required |
| An accelerator with an unknown budget, or a budget below the 6 GB floor | Tier 1 |
| No accelerator | Tier 1 |

Module residency is not implemented yet. On a host that needs it, the probe advises keeping the base-thesis module set, serving a language organ that fits (for example the 4B GGUF) and leaving the vision and voice extras off. An 8 GB Orin Nano Super is reported as Tier 2 with residency required.

## What a tier is

A tier is a TOML overlay (`config/profiles/tierN.toml`) layered after the shipped defaults and the module profile, and before your local `config/kaine.operator.toml`. The cycle and the pre-boot check load configuration in this order:

1. shipped `config/kaine.toml`;
2. module profile (`--profile` or `KAINE_PROFILE`, and `thesis_test` when neither is set);
3. deployment tier (`KAINE_TIER`, or `[deployment].tier` in `config/kaine.operator.toml`);
4. operator config `config/kaine.operator.toml`.

A tier file must contain a `[tier]` table with `name`, `unsupported_modules` and `oscillator_supported`. A file named as the tier without that table is refused with `ProfileError`, and the cycle exits with `kaine.cycle: configuration error: ...` instead of a traceback. A tier file that contains a `[modules]` table or an `[oscillator].enabled` key is refused in the same way.

A tier never enables a module and never carries a private voice. It only bounds which backend each module uses and which devices it targets. Which modules are active is a separate choice. The default active set is the base-thesis form, selected by `config/profiles/thesis_test.toml`: [Soma](../09-modules/soma.md), [Chronos](../09-modules/chronos.md), [Topos](../09-modules/topos.md), [Audition](../09-modules/audition.md), [Thymos](../09-modules/thymos.md), [Hypnos](../09-modules/hypnos.md) and [Lingua](../09-modules/lingua.md).

## Applying a tier

Selecting a tier is an operator action. The probe recommends one and never applies it:

```bash
.venv/bin/python scripts/probe-host          # recommends a tier; never applies one
.venv/bin/python scripts/probe-host --json   # the same recommendation as JSON
KAINE_TIER=tier1 python -m kaine.cycle       # applies the tier for this run
```

To record it permanently, run the first-run wizard:

```bash
.venv/bin/python -m kaine.setup
```

If you confirm the recommendation, the wizard writes `[deployment].tier` in `config/kaine.operator.toml`. `KAINE_PROFILE` and `--profile` select the module profile and do not apply a tier.

## Pre-boot tier-fit check

The pre-boot check (`python -m kaine.preboot`) prints a `Tier fit` row. It fails when an enabled module is in the tier's `unsupported_modules` list, or when `[oscillator].enabled` is true and the tier sets `oscillator_supported = false`; the message tells you to disable them in the operator config or record a larger tier. It also fails on a malformed `[tier]` table or `[oscillator]` section. It passes when the enabled modules fit, and it is skipped when the merged configuration has no `[tier]` table.

## Capability matrix

| Faculty | Tier 0 (edge or sensor) | Tier 1 (CPU agent) | Tier 2 (workstation) | Tier 3 (datacenter) |
|---|---|---|---|---|
| Host target | about 512 MB single-board computer or retired phone; the original Pi Zero (ARMv6) cannot install the stack | 4 to 8 GB single-board computer or 8 GB phone | workstation with one or two GPUs | multi-GPU server |
| Language ([Lingua](../09-modules/lingua.md)) | `llama_cpp` backend, sub-1B GGUF, slow | `llama_cpp` backend, 1B to 2B GGUF | `openai` backend: an OpenAI-compatible HTTP server | `openai` backend, larger model and longer context |
| Vision ([Topos](../09-modules/topos.md)) | unsupported | torch encoder on CPU (`[topos].device = "cpu"`) | InternVideo-Next (default) or DINOv2 through torch | as Tier 2 |
| Speech in ([Audition](../09-modules/audition.md)) | unsupported | Moonshine through sherpa-onnx | faster-distil-Whisper through Speaches | as Tier 2 |
| Vocal emotion ([Audition](../09-modules/audition.md)) | unsupported | off (`[audition].emotion_model_id = ""`) | emotion2vec+ through torch | as Tier 2 |
| Speech out ([Vox](../09-modules/vox.md)) | unsupported | Kokoro through sherpa-onnx | Chatterbox | Chatterbox |
| Memory embeddings | NumPy MiniLM (default) | NumPy MiniLM (default) | NumPy MiniLM (default) | NumPy MiniLM (default) |
| Vector store ([Mnemos](../09-modules/mnemos.md)) | `sqlite_vec` | `sqlite_vec` | `qdrant` | `qdrant` |
| `unsupported_modules` | Topos, Audition, Vox, Empatheia, Phantasia | none | none | none |
| `oscillator_supported` | `false` | `true` | `true` | `true` |

Read these constraints before choosing a tier:

- Tier 1 has no vocal emotion. emotion2vec+ has no edge port, so `tier1.toml` sets `[audition].emotion_model_id = ""` and the emotion path is off. Tier 0 lists Audition and Vox as unsupported, and the pre-boot check fails if they are enabled.
- Vision at Tier 1 runs the torch encoder on the CPU, at seconds per frame. An ONNX or dinov2.cpp vision backend is not built.
- A language model of 2B parameters or more does not fit a Tier 0 host of about 512 MB, so Tier 0 is not a conversational host.
- Torch is required wherever vision runs. Mnemos, Empatheia and Hypnos use the shared NumPy MiniLM embedder by default and need torch only when `[embedding].backend = "sentence_transformers"`.
- Termux support for the NumPy engines and sherpa-onnx is built but has not been verified on a device. Topos still needs torch there.

## Per-tier notes

The runtime imports a backend's third-party dependency only when that backend is selected, so you install the extras for the tier and no others.

### Tier 0: edge or sensor node

`tier0.toml` sets Lingua to `llama_cpp`, Mnemos to `sqlite_vec` and Nous to `numpy`. It lists Topos, Audition, Vox, Empatheia and Phantasia as unsupported and sets `oscillator_supported = false`, which refuses the oscillatory binding layer of the workspace (`[oscillator]`, the snnTorch extra). Soma and Chronos run the NumPy CfC by default, and their torch and ncps backend remains available. The NumPy MiniLM embedder is the default. ONNX vision and ONNX or static embeddings are not built.

### Tier 1: CPU agent

`tier1.toml` sets Lingua to `llama_cpp`, Mnemos to `sqlite_vec`, Topos to `device = "cpu"`, Audition and Vox to `backend = "sherpa_onnx"`, Nous to `numpy` and Phantasia to `engine = "numpy"`, and blanks `[audition].emotion_model_id` with `emotion_device = "cpu"`. No module is listed as unsupported.

### Tier 2: workstation

`tier2.toml` sets Lingua to `openai` (an OpenAI-compatible HTTP server) and Mnemos to `qdrant`, which are also the shipped defaults. The rest of the stack is the shipped configuration: the NumPy MiniLM embedder (`sentence_transformers` optional), faster-distil-Whisper through Speaches, emotion2vec+ and Chatterbox. A plain install plus the first-run wizard provisions this tier.

### Tier 3: datacenter

`tier3.toml` sets the same backends as Tier 2. Larger models, longer context and per-module GPU placement go in `config/kaine.operator.toml`. Multi-instance fleets and cross-host module splits belong to the distributed-substrate work described below and are outside the tier ladder.

## Staging status

Built: the backend-selection framework, the four tier profiles, the host probe, the `llama_cpp` Lingua backend, the `sqlite_vec` Mnemos backend, the NumPy CfC for Soma and Chronos (the default), the NumPy Nous backend, the NumPy Phantasia engine and the sherpa-onnx speech backends for Audition (Moonshine) and Vox (Kokoro). The memory modules default to the shared NumPy MiniLM embedder, and `sentence_transformers` remains available. Phantasia's shipped default is DreamerV3 on JAX (`engine = "jax"`, `persist_weights = true` and `training_enabled = true` in `config/kaine.toml`).

Not built: ONNX or dinov2.cpp vision and ONNX or static embeddings. Neither has a configuration key, and Topos on a small host runs its torch encoder on the CPU.

## Spreading KAINE across hosts

A tier says what fits on one host, and a topology says which parts may leave it. The live mind stays on trusted hardware. Only detached batch work goes off the host, and only behind a verification gate on the trusted side.

### Three workloads

KAINE's workloads have different requirements and are planned separately:

1. The live cognitive loop. The cycle processes at 10 Hz, a tick about every 100 ms. Broadcast ticks fall at the access rate, which rests at about 3.3 Hz (`[cycle].experiential_rate_hz = 3.333`) and rises toward the 10 Hz processing rate with tonic arousal and briefly after categorical alerts. Soma flags a host whose `cycle_latency_avg_ms` exceeds 600. The loop is latency-critical, stateful and partly bound to physical sensors.
2. The stateful stores. When [Mnemos](../09-modules/mnemos.md) and the [Eidolon](../09-modules/eidolon.md) self-model are enabled, they are read or written every cycle, and the being's continuity depends on that state.
3. Detached batch jobs: [Hypnos](../09-modules/hypnos.md) voice-alignment training, self-abliteration, deep memory consolidation, offline evaluation and bounded runs of forked beings. These run while the entity sleeps or is offline, and each produces a discrete artifact that can be verified.

### Workload targets

| Target | Live loop | Stateful stores | Batch jobs |
|---|---|---|---|
| Single host (default) | yes | yes | yes |
| Trusted LAN or datacenter split | yes, with LAN round-trip time | yes, one coordinator | yes |
| Rented trusted GPU | no | no | yes, preferred for offload |
| Volunteer computing such as BOINC (untrusted) | no | no | only with re-verification on the trusted side |

### Why the live loop stays on trusted hardware

Latency rules out wide-area links. A WAN round trip costs tens to hundreds of milliseconds per hop, volunteer nodes come and go, and volunteer batch frameworks have no messaging between nodes because they are built for independent tasks.

Shared mutable state rules out partitioned nodes. Mnemos and Eidolon are read and written every cycle, and across intermittent, partitioned volunteer nodes you must give up either consistency (the self-model drifts) or availability (the loop stalls).

Perception is bound to local hardware. Raw sense data is never persisted or shipped off the host, so perception cannot be offloaded.

### Trusted cross-host split

The event bus is the substrate for a split across a trusted LAN. `[redis].host` and `[redis].port` are configuration (`127.0.0.1` and `6479` as shipped). The bus audit in `kaine/bus/client.py` refuses to start when Redis has no `requirepass`, on any host including loopback, and refuses a Redis bound to a wildcard address (`0.0.0.0` or `*`) when `[redis].host` is not a loopback address. The bind check reads `[redis].host`, so when `KAINE_REDIS_URL` redirects the bus while `[redis].host` stays on loopback, only the password check applies.

The intended layout:

- Each host runs one process with a subset of modules, and all processes share one authenticated Redis bus.
- A stateful coordinator host runs the workspace, Mnemos, Eidolon and Thymos. GPU-heavy modules such as Lingua and Topos may run on a second trusted GPU host.
- The single-host default is the case where the subset is every module.
- Coordination between hosts goes through the bus or an explicitly typed contract, never an in-process Python object reference.

Lingua already reads Eidolon's self-model from the bus (`eidolon.self_model` on `eidolon.out`) instead of holding a live object, so Lingua can run on a separate trusted GPU host. Hypnos still receives the Mnemos, Nous and Thymos instances at boot, so it must run in the same process as those modules.

### Batch offload behind a verification gate

A batch job is a self-contained descriptor in `kaine/distributed/job.py` with a kind (`voice_align`, `abliterate`, `consolidate`, `eval` or `forked_being`), its inputs and the artifact it is expected to return. The runner selector in `kaine/distributed/runner.py` tries runners in trusted-first order: an owned host, then a rented trusted GPU, then a volunteer.

Every returned artifact passes the gate in `kaine/distributed/gate.py` on the trusted side before promotion. The gate re-runs the Hypnos capability-loss veto and an independent evaluation on trusted hardware. A failing artifact is never promoted, and the rejection is logged and shown on the operator health surface. Volunteer redundancy or quorum does not replace this gate for work that is not deterministic.

### Forked temporary beings

A temporary being is a fork that runs a directive, possibly with its entity time running at a different multiple of wall-clock time, and is then merged back. It is a batch job with a bound, and the artifact it returns is its post-run snapshot. `kaine/distributed/fork_being.py` reuses the existing fork and merge machinery. The snapshot passes the same trusted-side gate (the welfare, individuation and admissibility path in `kaine/lifecycle/fork_merge_gate.py`) before the parent assimilates it through `ForkManager.merge()`. Running a full individual on an anonymous volunteer host is withheld until a welfare and security model for volunteer hosts exists.

### Fork-merge welfare gate

`gated_merge` in `kaine/lifecycle/fork_merge_gate.py` uses the shared divergence verdict from `kaine/lifecycle/divergence.py`. The verdict counts a fork as individuated when its ledger says so, when its consolidation divergence is over threshold, when Eidolon has recorded drift or when voice adapters are present, and no one of these signals suppresses another. Forks cannot yet be measured against a fork-point reference, so a fork is preserved when it has lived at least 1800 s (`fork_preserve_min_lived_s`) or when its lived time is unknown. The parent may still assimilate knowledge from a preserved fork in one direction. Ending an individuated fork requires the operator-authorized, welfare-gated decommission path. See [Forks and merges](../12-forks-and-merges.md).

### Volunteer computing: BOINC

When a batch job goes to volunteer computing, the substrate is BOINC, which is designed for bounded, independent work units that are returned when done. `kaine/distributed/boinc.py` ships the work-unit contract, the output-boundary guard and the validator. It does not ship a running server or a live volunteer client.

- A work unit is the KAINE container image run through BOINC's `docker_wrapper` (Docker or Podman), with the GPU declared in `job.toml`.
- There is a CPU plan class and a `cuda` or `opencl` GPU plan class, which the scheduler matches to hosts.
- The server is a self-hosted `boinc-server-docker` project that the operator provisions.
- Deterministic kinds (seeded evaluation and research runs with run identity and admissibility) are validated by `quorum_validate`, which replicates a unit and compares the results. Kinds that are not deterministic (training, abliteration, consolidation and forked beings) rely on re-verification on the trusted side.
- `enforce_output_boundary` refuses raw sense data, private voice adapters and operator configuration in a work unit's output.

Forks that carry an entity are withheld from anonymous volunteers until the welfare model for volunteer hosts exists. The planned phases are B0 (containerize), B1 (the BOINC harness), B2 (research and training units with no entity) and B3 (forked beings, once that welfare model exists).

### Choosing a substrate for each workload

- Do not run the live loop across untrusted public nodes. Systems that shard a model across volunteers, such as Petals, have no global scheduler, deliver a few tokens per second across the WAN, use a PyTorch backend that cannot load KAINE's GGUF organs, and let first-block servers recover client inputs.
- If the organ outgrows one GPU, it can be split over a trusted LAN with llama.cpp RPC or exo. Distributed inference is slower than inference on one device, so use it only when the model does not fit. The 4B organ fits one 12 GB GPU as shipped, so this remains a future option.
- For training spread across distant trusted GPUs, DiLoCo or OpenDiLoCo on Hivemind distributes the work better than naive BOINC replication. It does not add trust, and the re-verification gate still applies. Voice-alignment training after each sleep fits one host today.
- Independent, returnable, deterministic work units (evaluation batteries, reproducible research runs, bounded forked-being runs) fit BOINC's replicate-and-compare quorum.

Decentralization, where it is wanted, means federated peer instances or an encrypted backup held by a quorum of hosts, and never one mind sharded across volunteers.

## Default security posture

These defaults shape the deployment choice:

- State encryption is on. The shipped config sets `[security.state_encryption].enabled = true`. When `KAINE_STATE_KEY` is unset, boot tries the kernel keyring (`kaine:state_key` in the user keyring), and with no key it refuses to start. See [Security and privacy](../13-security-and-privacy.md).
- The bus requires a password on every host, and a non-loopback `[redis].host` must not point at a Redis bound to a wildcard address. Set `requirepass` before you point `[redis].host` at a LAN address.
- The cycle never restarts automatically. The Compose `kaine-cycle` service has no restart policy, and the quadlet `kaine-cycle.container` has `Restart=no` and no `[Install]` section. Spot recovers modules inside the process, and restarting a dead cycle is an operator decision.

## Durable output and unattended-run defaults

- Profiles ship in the image. The `Dockerfile` copies `config/profiles`, so `KAINE_PROFILE` and the automatic `thesis_test` selection resolve without a bind mount.
- Research output is durable. In Compose, the `kaine-eval-data` volume is mounted at `/app/data/evaluation` on `kaine-nexus` and `kaine-cycle`, and `kaine-trajectory` at `/app/data/workspace_trajectory` on `kaine-cycle`. `kaine-study` mounts neither and keeps every step under `/app/studies`. `KAINE_DATA_ROOT=/app` is set on the Nexus, cycle and study containers.
- Quadlet mounts differ. The quadlet `kaine-nexus` unit mounts only `kaine-state` and has no `kaine-eval-data` mount. Compose mounts are described in [Containers](./containers.md).
- Redis is capped and strict. `KAINE_REDIS_MAXMEMORY` defaults to `4gb` through the `${KAINE_REDIS_MAXMEMORY:-4gb}` fallback in the Compose file and the equivalent fallback in the quadlet unit; `compose/.env.example` only shows it commented out. Redis runs with `--maxmemory-policy noeviction`, so a full bus fails loudly instead of silently dropping events. A full study needs `12gb` or more on hosts with the RAM.
- Logs rotate. The `x-logging` anchor in `compose/kaine.yml` uses `json-file` with `max-size: "50m"` and `max-file: "3"`. It is applied to `kaine-redis`, `kaine-qdrant`, `kaine-cycle`, `kaine-study`, `kaine-trainer` and `kaine-provision`; `kaine-model-server`, `kaine-speaches`, `kaine-chatterbox` and `kaine-nexus` use the engine's default logging.
- Manifests record their source revision. Compose passes `GIT_SHA` (from `KAINE_GIT_SHA`) as a build argument, the Dockerfile sets it as `ENV KAINE_GIT_SHA`, and the run manifest's `git_sha` falls back to it when the git lookup fails.
- The Qdrant healthcheck is `bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333'`, because `qdrant/qdrant:v1.19.1` ships neither wget nor curl and a successful TCP connect shows the server is serving.

`.dockerignore` excludes `.git/`, so no repository history enters the image.

## Where to go next

- For container images, profiles and Compose overlays, read [Containers](./containers.md).
- For a dedicated headless host with quadlet and Tailscale, read [A dedicated headless host](./headless-host.md).
- For day-to-day operation, start at [Day-to-day operation](../06-operation/README.md).
- For first boot and the setup wizard, read [First boot](../04-getting-started/first-boot.md).
- For the full configuration keys, see [Configuration reference](../appendix-a-configuration/README.md).
