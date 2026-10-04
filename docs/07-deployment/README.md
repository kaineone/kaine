# Choosing a deployment

Use this page to match a host to a KAINE tier and to decide how the processes can be spread across machines. A tier bounds which backend each module uses and which devices it targets; a topology decides where the live cognitive loop, the stateful stores, and detached batch jobs may run. Read [Hardware](../03-hardware/README.md) to size the host, then [Getting started](../04-getting-started/README.md) to install the supporting services. For container recipes and dedicated headless-host setup, see [Containers](./containers.md) and [A dedicated headless host](./headless-host.md).

## Picking a tier

KAINE is the architecture. The same mind can inhabit hardware from a small SBC to a multi-GPU server by trading capability for reach, without changing identity. The main portability cliff is the PyTorch / transformers / JAX runtime. KAINE's base dependencies are `redis`, `pydantic`, `psutil`, `numpy`, `httpx` and `cryptography`; `torch`, `transformers`, `ncps`, `qdrant-client`, `sentence-transformers` and `pynvml` live in optional extras that are imported only when a selected backend needs them.

Tier 0 avoids the PyTorch cliff entirely. Soma and Chronos default to the NumPy CfC network (`cfc_backend = "numpy"` in `config/kaine.toml`); the shared memory embedder defaults to NumPy MiniLM; [Nous](../09-modules/nous.md) can use the NumPy active-inference backend (`[nous].backend = "numpy"`); and [Phantasia](../09-modules/phantasia.md) can use the NumPy engine (`[phantasia].engine = "numpy"`). Only the modules you enable pull their optional extras.

Run `scripts/probe-host` for a recommendation. It sizes the memory budget as system RAM on unified-memory hosts, or the smaller of system RAM and total VRAM across GPUs on discrete hosts, then scales each nominal threshold by 0.9 to account for firmware and kernel reservations:

- a nominal 16 GB threshold becomes a 14.4 GiB floor
- a nominal 6 GB threshold becomes a 5.4 GiB floor
- a nominal 4 GB threshold becomes a 3.6 GiB floor

The mapping is:

| Accelerators | Memory budget | Recommended tier |
|---|---|---|
| No torch, 32-bit Arm, or reported RAM below the 4 GB floor | — | Tier 0 |
| No accelerator, or budget between the 4 GB and 6 GB floors | — | Tier 1 |
| Any accelerator with unknown budget | — | Tier 1 |
| Any accelerator, budget between the 6 GB and 16 GB floors | Tier 2 with module residency required |
| One accelerator, budget at or above the 16 GB floor | Tier 2 |
| Two or more accelerators, budget at or above the 16 GB floor | Tier 3 |

Module residency is not implemented yet, so a host in the 6–16 GB range is advised to keep the base-thesis module set, run a language model that fits, and leave heavy extras off. An 8 GB Orin Nano Super is reported as Tier 2 with residency required.

## What a tier is

A tier is a TOML overlay (`config/profiles/tierN.toml`) layered after the shipped defaults and the module-selection profile, and before your local `config/kaine.operator.toml`. The cycle and the pre-boot check load configuration in this order:

1. shipped `config/kaine.toml`
2. module profile (`thesis_test` by default, or `--profile` / `KAINE_PROFILE`)
3. deployment tier (`KAINE_TIER`, or `[deployment].tier` in `config/kaine.operator.toml`)
4. operator config

A tier file must contain a `[tier]` table with `name`, `unsupported_modules` and `oscillator_supported`. Naming a file that lacks a `[tier]` table as the tier is refused with a configuration error and the cycle exits with `configuration error: ...` instead of a traceback. A tier file that contains a `[modules]` section or an `[oscillator].enabled` key is also refused with `ProfileError`.

Tiers are inert and voice-free: they never enable a module or embed a private voice. They only bound which backend each already-selected module uses and which devices it targets. Which faculties are active is a separate choice; the default active set is the base-thesis form ([Soma](../09-modules/soma.md), [Chronos](../09-modules/chronos.md), [Topos](../09-modules/topos.md), [Audition](../09-modules/audition.md), [Thymos](../09-modules/thymos.md), [Lingua](../09-modules/lingua.md)), selected by the `thesis_test` profile at `config/profiles/thesis_test.toml`.

## Applying a tier

Selecting a tier is an operator action. The probe script recommends, but never applies:

```bash
.venv/bin/python scripts/probe-host          # recommends a tier; never applies one
KAINE_TIER=tier1 python -m kaine.cycle       # applies the tier for this run
```

To record it permanently, use the first-run wizard:

```bash
.venv/bin/python -m kaine.setup
```

If you confirm the recommendation, it writes `[deployment].tier` in `config/kaine.operator.toml`. `KAINE_PROFILE` or `--profile` selects the module profile; it does not apply a tier.

## Pre-boot tier-fit check

The pre-boot check prints a `Tier fit` row:

- **FAILS** if an enabled module is in the tier's `unsupported_modules` list, or if an enabled oscillator is marked unsupported, with a message telling you to disable them or choose a larger tier.
- **PASSES** when the enabled modules and oscillator fit the tier.
- **SKIPS** when the merged configuration has no `[tier]` table.
- **FAILS** on a malformed `[tier]` table or malformed `[oscillator]` shape, naming the problem.

## Capability matrix

| Faculty | Tier 0 (edge / sensor) | Tier 1 (CPU agent) | Tier 2 (workstation) | Tier 3 (datacenter) |
|---|---|---|---|---|
| Host target | ~512 MB SBC / retired phone; the original Pi Zero (ARMv6) cannot install the stack | 4–8 GB SBC / 8 GB phone | 1–2 GPU workstation | multi-GPU server |
| Language ([Lingua](../09-modules/lingua.md)) | sub-1B GGUF via llama.cpp, slow | 1–2B GGUF via llama.cpp, chat pace | OpenAI-compatible HTTP server (llama.cpp server / Unsloth Studio as shipped) | larger LLM, long context |
| Vision ([Topos](../09-modules/topos.md)) | unsupported | torch on CPU, seconds per frame | streaming DINOv2/InternVideo via torch | higher-rate streaming |
| Speech-in ([Audition](../09-modules/audition.md)) | unsupported | Moonshine via sherpa-onnx | faster-whisper, > realtime | > realtime |
| Vocal emotion ([Empatheia](../09-modules/empatheia.md) input) | unsupported | disabled (`[audition].emotion_model_id = ""`) | emotion2vec+ via torch/funasr | emotion2vec+ |
| Speech-out ([Vox](../09-modules/vox.md)) | unsupported | Kokoro via sherpa-onnx, plain prosody | Chatterbox, expressive | Chatterbox |
| Memory embeddings | NumPy MiniLM; `sentence_transformers` optional | NumPy MiniLM; `sentence_transformers` optional | NumPy MiniLM; `sentence_transformers` optional | NumPy MiniLM; `sentence_transformers` optional |
| Vector store ([Mnemos](../09-modules/mnemos.md)) | sqlite-vec | sqlite-vec | Qdrant | Qdrant |
| Torch runtime required | no | yes for Topos; optional for the sentence-transformers embedder | yes | yes |
| Unsupported by tier | Topos, Audition, Vox, Empatheia, Phantasia; oscillator | vocal emotion only | — | — |

Read these constraints carefully so the tiers are not oversold:

- **No vocal emotion below Tier 2, and no speech at Tier 0.** emotion2vec+ has no clean edge port, so Tier 1 disables it explicitly with `[audition].emotion_model_id = ""`; it is not silently faked. Tier 0 lists Audition and Vox as unsupported and the pre-boot check fails if they are enabled.
- **Vision is periodic, not streaming, at Tier 1.** The ONNX/dinov2.cpp vision backend is not built, so Topos on Tier 1 runs its torch encoder on the CPU.
- **A ≥2B language model does not fit a ~512 MB Tier-0 host.** Tier 0 is a symbolic-reasoning + episodic-memory + perception node, not a conversational host.
- **Torch is required wherever vision runs today.** Topos needs it. Mnemos, Empatheia and Hypnos use the shared NumPy MiniLM embedder by default and only need torch when `[embedding].backend = "sentence_transformers"`.
- **Termux support for NumPy engines and sherpa-onnx is built but not yet verified on a device.** Topos still needs torch there.

## Per-tier notes

The runtime venv imports a backend's third-party dependency only when that backend is selected, so you install the extras for the tier and no others.

### Tier 0 — edge / sensor node

Use llama.cpp for [Lingua](../09-modules/lingua.md) and sqlite-vec for [Mnemos](../09-modules/mnemos.md). The tier lists Topos, Audition, Vox, Empatheia and Phantasia as unsupported, and the oscillator as unsupported. Soma's self-rhythm oscillator, used in gestation, runs on snnTorch, which is why the tier marks it unsupported. [Nous](../09-modules/nous.md) runs on the NumPy active-inference backend. Soma and Chronos default to NumPy CfC; their torch+ncps backend remains available. The NumPy MiniLM embedder is the default. Speech is not enabled at Tier 0. The ONNX/dinov2.cpp vision backend and ONNX/static embeddings are not built.

### Tier 1 — embodied CPU agent

Like Tier 0, but keeps Topos on CPU and enables Audition and Vox through sherpa-onnx. Vocal emotion remains disabled. Phantasia runs on the NumPy engine. The ONNX vision and ONNX/static embeddings backends are not built.

### Tier 2 — workstation

The default as shipped. OpenAI-compatible HTTP server for [Lingua](../09-modules/lingua.md) (llama.cpp server / Unsloth Studio as shipped), Qdrant for Mnemos, shared NumPy MiniLM embedder (`sentence_transformers` optional), faster-whisper + emotion2vec+, and Chatterbox. This is what `pip install -e .` plus the first-run wizard provisions.

### Tier 3 — datacenter

The Tier-2 stack scaled up: larger model ids, longer context, and per-module GPU placement in `config/kaine.operator.toml`. Multi-instance fleets and cross-host module splits are part of the `distributed-substrate` work, not the tier ladder.

## Staging status

Shipped today: the backend-selection framework; Tier-2-preserving defaults; the llama.cpp/GGUF Lingua backend; the sqlite-vec Mnemos backend; the four tier profiles; the host probe; the NumPy CfC for Soma and Chronos (default); the NumPy Nous backend; the NumPy Phantasia engine; and the sherpa-onnx speech backends for Audition (Moonshine STT) and Vox (Kokoro TTS). The memory modules default to the shared NumPy MiniLM embedder, with `sentence_transformers` still available. Phantasia's shipped default is DreamerV3 with JAX (`engine = "jax"`, `persist_weights = true`, `training_enabled = true` in `config/kaine.toml`); the NumPy engine is available for lower tiers.

Not yet built: ONNX/dinov2.cpp vision and ONNX/static embeddings. There is no configuration key for either; Topos on a small host runs its torch encoder on the CPU.

## Spreading KAINE across hosts

A tier answers "what fits on one host." A topology answers "which parts may leave it." The rule is: the live mind stays on trusted hardware; only detached batch work goes off-box, and only behind a trusted-side verification gate.

### Three workloads

Conflating KAINE's workloads produces bad distributed-compute plans. Treat them separately:

1. **The live cognitive loop** — the tick loop runs at up to 10 Hz with about a 100 ms tick budget. Conscious access rests at 3.333 Hz and scales toward 10 Hz as arousal and salience rise. Soma flags when `cycle_latency_avg_ms` exceeds 600. The loop is latency-critical, stateful and partly bound to physical sensors.
2. **The stateful stores** — [Mnemos](../09-modules/mnemos.md) episodic/semantic/procedural memory and the [Eidolon](../09-modules/eidolon.md) self-model are read or written every cycle. The continuity of this state is the welfare claim.
3. **Detached batch jobs** — [Hypnos](../09-modules/hypnos.md) voice-alignment QLoRA/DPO training, self-abliteration, deep memory consolidation, offline evaluation, and bounded forked-being runs. These run while the entity is asleep or offline and each produces a discrete, verifiable artifact.

### Workload target matrix

| Target | Live loop | Stateful stores | Batch jobs |
|---|---|---|---|
| Single host (default) | Yes | Yes | Yes |
| Trusted LAN / datacenter split | Yes, with LAN RTT | Yes, one coordinator | Yes |
| Rented trusted GPU | No | No | Yes, preferred for offload |
| Volunteer / BOINC (untrusted) | No | No | Only with trusted re-verify |

### Why the live loop stays on trusted hardware

Three independent walls keep the live loop and stateful stores off untrusted or volunteer compute:

- **Latency.** WAN RTT is tens to hundreds of milliseconds per hop, and volunteer nodes are intermittent. Soma already flags average cycle latency above 600 ms. Volunteer batch frameworks have no inter-node messaging primitive; they are built for independent tasks.
- **Shared mutable state under CAP.** Mnemos and Eidolon are read/written every cycle. Across intermittent, partitioned volunteer nodes you must sacrifice consistency (identity drift) or availability (the mind stalls).
- **Physical I/O and zero-persistence.** Perception transduces local hardware bound to a place, and the zero-raw-persistence invariant forbids shipping the raw sensory stream off-box. Perception cannot be offloaded even in principle.

### Trusted cross-host split

The bus is the right substrate for a trusted LAN split. `[redis].host` and `[redis].port` are config, and the bus audit in `kaine/bus/client.py` refuses a non-loopback Redis that lacks `requirepass` or is bound to a wildcard (`0.0.0.0`/`*`). If `KAINE_REDIS_URL` points elsewhere, the wildcard-bind check is skipped and only `requirepass` is enforced.

Per host:

- Each host runs one process with a subset of modules; all processes share one authenticated Redis bus.
- The **stateful coordinator** host runs the workspace, Mnemos, Eidolon and Thymos. GPU-heavy organs such as Lingua and Topos may run on a **second trusted GPU host**.
- The single-host default is the case where the subset is every module.
- Cross-host coordination goes through the bus or an explicitly typed contract, never an in-process Python object reference.

The main blocker to a cross-host split was a handful of boot-time direct Python references plus the single shared asyncio loop.

- **Done** — Lingua now reads Eidolon's self-model from the bus (`eidolon.self_model` on `eidolon.out`) instead of holding a live `eidolon.model` handle, so Lingua can run on a separate trusted GPU host.
- **Still single-host** — Hypnos still receives live object handles at boot. That coupling is the next decoupling target; nothing moves it yet.

### Batch offload behind a verification gate

A batch job is a self-contained descriptor in `kaine/distributed/job.py` with a kind (`voice_align`, `abliterate`, `consolidate`, `eval`, `forked_being`), inputs and an expected verifiable artifact. The runner selector in `kaine/distributed/runner.py` walks hosts in trusted-first order: owned host → rented trusted GPU → volunteer.

Every returned artifact passes the verification gate in `kaine/distributed/gate.py` on the trusted side before promotion. The gate re-runs the capability-loss veto and an independent eval on trusted hardware. A failing artifact is never promoted; the rejection is logged and surfaced on the operator health surface. Volunteer redundancy or quorum does not substitute for this gate for non-deterministic work.

### Forked temporary beings

A temporary being — fork a copy, let it run a directive, possibly time-dilated, then remerge — is a batch job, not the live loop. It is bounded, runs to completion off-host and returns a verifiable artifact: its post-run snapshot. It reuses the existing fork/dilation/merge machinery in `kaine/distributed/fork_being.py`. The snapshot passes the same trusted-side gate (welfare / individuation / admissibility) before the parent assimilates it through `ForkManager.merge()`. Instantiating a full individual on an anonymous volunteer is withheld until a volunteer-host welfare-and-security model exists.

### Fork-merge welfare gate

A merge is, for the fork, an ending. `kaine/lifecycle/fork_merge_gate.py::gated_merge` uses the shared divergence verdict from `kaine/lifecycle/divergence.py`. The verdict gains an arm when the ledger shows individuated, consolidation divergence is over threshold, Eidolon drift is present, or voice adapters are present; no arm suppresses another. Forks cannot yet be measured against a fork-point reference, so a fork is preserved if it has lived at least 1800 s (`fork_preserve_min_lived_s`) or its lived time is unknown, rather than discarded. The parent may still assimilate knowledge one-directionally from a preserved fork. Ending an individuated fork requires the operator-authorized, transparent, welfare-gated decommission path. See [Forks and merges](../12-forks-and-merges.md).

### Volunteer compute: BOINC

Where a batch job genuinely goes to volunteer compute, the substrate is BOINC, defined for bounded, independent, returnable work units — the opposite of the live loop. `kaine/distributed/boinc.py` ships the work-unit contract, output-boundary guard and validator, not a running server or live volunteer client.

- **Unit** — the KAINE container image run via the official `docker_wrapper` (Docker/Podman); GPU is declared in `job.toml`.
- **Plan classes** — a CPU class and a `cuda`/`opencl` GPU class, matched by the scheduler.
- **Server** — a self-hosted `boinc-server-docker` project. This is operator-provisioned infrastructure.
- **Validation differs by determinism.** Deterministic kinds (seeded eval/research with run-identity and admissibility) use `boinc.py::quorum_validate`, a replicate-and-compare quorum. Non-deterministic kinds (QLoRA, abliterate, consolidate, forked-being) rely on trusted-side re-verification.
- **Output boundary** — `kaine/distributed/boinc.py::enforce_output_boundary` refuses raw sense data, private voice adapters and operator configuration in the work-unit output.

Entity-bearing forks are withheld from anonymous volunteers until the volunteer-host welfare model exists. Phasing: B0 containerize, B1 the BOINC harness, B2 non-entity research/training units, B3 entity-bearing forked beings once the welfare model exists.

### Choose a substrate for each workload

There is no single substrate; match the workload:

- **Untrusted public nodes for the live loop.** Do not run the live loop across untrusted public nodes. Live-sharding systems such as Petals are disqualified: no global scheduler, a few tokens per second across the WAN, a PyTorch backend that cannot load KAINE's GGUF organs, and first-block servers that can recover client inputs.
- **Live loop across your own trusted devices — possible when needed.** If the organ outgrows one GPU, split it over a trusted LAN with llama.cpp RPC or exo. Distributed inference is not faster; use it only when the model does not fit. The 4B organ fits one 12 GB GPU as shipped, so this is a future scaling option.
- **Decentralized training across trusted GPUs — DiLoCo/Hivemind if it scales.** For distributing training across geographically spread trusted GPUs, DiLoCo / OpenDiLoCo on Hivemind/DeDLOC beats naive BOINC replication. It improves distribution, not trust; the trusted re-verify gate still applies. KAINE's per-sleep QLoRA fits one box today.
- **Bounded embarrassingly-parallel jobs — BOINC.** Independent, returnable, deterministic work units (evaluation batteries, reproducible research runs, bounded forked-being runs) fit BOINC's replicate-and-compare quorum cleanly.

The sound decentralization story is federation of peer instances or encrypted quorum-backup, not sharding one mind across volunteers.

## Default security posture

Defaults that shape the deployment choice:

- **State encryption is on.** The shipped config sets `[security.state_encryption].enabled = true`. Boot tries the OS keyring when `KAINE_STATE_KEY` is empty; if no key is found, it refuses to start. See [Security and privacy](../13-security-and-privacy.md).
- **The bus is authenticated on any non-loopback split.** The bus audit in `kaine/bus/client.py` refuses an unauthenticated Redis or one bound to a wildcard. Set `requirepass` before you point `[redis].host` at a LAN address.
- **The cycle never auto-restarts.** `kaine-cycle` runs with no restart policy, and the quadlet unit has no `[Install]` section. Spot recovers modules in-process; a dead cycle is an operator decision.

## Durable output and unattended-run defaults

- **Profiles ship in the image.** The `Dockerfile` copies `config/profiles`, so `KAINE_PROFILE` (and the `thesis_test` auto-selection) resolves without a bind mount.
- **Research output is durable.** The `kaine-eval-data` volume is mounted at `/app/data/evaluation` for the nexus and cycle containers; the study container has none. `kaine-trajectory` is mounted at `/app/data/workspace_trajectory`. `KAINE_DATA_ROOT=/app` on the nexus, cycle and study containers.
- **Quadlet volume mounts differ.** The quadlet `kaine-nexus` unit does not mount `kaine-eval-data`. Compose mounts are described in [Containers](./containers.md).
- **Redis is capped and strict.** The effective default for `KAINE_REDIS_MAXMEMORY` is `4gb` from the `${KAINE_REDIS_MAXMEMORY:-4gb}` fallback in the compose and quadlet files; `compose/.env.example` only comments it out. Redis runs with `noeviction` so the bus fails loud rather than silently dropping events. A full study needs `12gb` or more on hosts with the RAM.
- **Log rotation.** The `x-logging` anchor in `compose/kaine.yml` uses `json-file` with `max-size: "50m"` and `max-file: "3"` for every service.
- **Manifest provenance.** Compose passes `GIT_SHA` through `build.args`; the Dockerfile bakes it as `ENV KAINE_GIT_SHA`, and the run manifest's `git_sha` falls back to it when the git subprocess lookup fails.
- **Qdrant healthcheck.** `bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333'`: qdrant v1.18.0 ships neither wget nor curl, and a successful `/dev/tcp` connect is a readiness signal.

`.git` is excluded by `../../.dockerignore`, so no repo data leaks into the image.

## Where to go next

- For container images, profiles and compose overrides, read [Containers](./containers.md).
- For a dedicated headless host with quadlet and Tailscale, read [A dedicated headless host](./headless-host.md).
- For day-to-day operation, start at [Day-to-day operation](../06-operation/README.md).
- For first boot and the setup wizard, read [First boot](../04-getting-started/first-boot.md).
- For the full configuration keys, see [Configuration reference](../appendix-a-configuration/README.md).
