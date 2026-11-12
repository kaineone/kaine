<!-- SPDX-License-Identifier: LicenseRef-CAL-0.5 -->
<!-- Copyright (c) 2026 Kaine.One -->

# Module residency

KAINE's modules draw on backends of different sizes: the language organ, an STT service, a TTS service, a vision encoder. On a host with enough memory, every backend stays loaded. On a smaller host they cannot all fit at once, so something has to give. The residency system is the part of KAINE that decides what stays loaded, what gets unloaded, and when to bring something back.

It enforces one memory budget per host, tracks which components are loaded in a ledger, and loads and unloads them as demand changes. A pinned component (the language organ by default) stays resident at all times; everything else rotates through the budget on demand.

The code lives in `kaine/residency/`.

## The budget

The residency budget answers one question: how many bytes can this host's backends share?

On a discrete-GPU host, each GPU gets its own device-domain budget derived from its VRAM. On a unified-memory host (Jetson, Apple Silicon), the GPU and CPU share the same pool, so there is one system-domain budget derived from physical RAM. On a CPU-only host the budget comes from system RAM alone. A cgroup memory limit, when present, is respected: the budget is clamped to whichever is smaller, physical RAM or the cgroup limit. A configurable reserve is subtracted from the available figure before the budget is set. The default reserve is the larger of 1 GiB and 10% of physical RAM.

Two commands show the budget on the running host:

```bash
scripts/probe-host              # prints a tier recommendation and the computed budget
python -m kaine.setup.footprint # prints calibrated component sizes and the fit report
```

`scripts/probe-host` computes the budget from the live host state. `python -m kaine.setup.footprint` also loads the footprint catalogue and produces a fit report that says whether the enabled components co-reside or must multiplex.

## The ledger and component states

The ledger (`kaine/residency/ledger.py`) tracks each registered component through five states:

```
ABSENT --> COLD --> LOADING --> RESIDENT --> UNLOADING --> COLD
```

- ABSENT: the component has never been registered.
- COLD: registered but not loaded. Its memory is free.
- LOADING: admitted by the ledger and currently loading. Its footprint counts against the budget from the moment of admission, so no other admission can overcommit.
- RESIDENT: loaded and available for use.
- UNLOADING: marked for teardown. No new requests are accepted. Once teardown finishes, the component returns to COLD.

A component is registered with its footprint in bytes and a TTL in seconds. The ledger enforces the budget: `try_admit()` checks that the headroom (budget minus the bytes used by LOADING and RESIDENT entries) can absorb the new component's footprint. If it can, the entry moves to LOADING and the admission succeeds. If it cannot, the caller must either evict something or wait.

## TTLs and the sweep

Each component has a TTL, the number of seconds it may sit idle before the sweep considers it for eviction. `run_ttl_sweep()` runs on a periodic interval (default 10 s) and calls `ttl_expired()` on the ledger. Any RESIDENT component that has not been used within its TTL, and is not pinned or in-flight, is unloaded.

The default TTL is 120 seconds, set by `[residency].ttl_seconds`. Per-component overrides go in `[residency].ttl_overrides`:

```toml
[residency]
ttl_seconds = 120

[residency.ttl_overrides]
kaine-speaches = 60
kaine-chatterbox = 90
```

## The pin

The language organ is pinned by default (`[residency].pin = "language"`). A pinned component is never evicted by the TTL sweep and is never offered as an eviction candidate. The reason is latency: a cold start of the language organ (loading a multi-gigabyte GGUF into GPU memory) takes seconds, and that delay would block every conversation turn. Keeping it resident means the entity can always think without a cold start.

Other components load on demand. When the entity needs STT, for example, the residency manager loads the Speaches service, uses it, and lets the TTL sweep reclaim its memory if nothing else needs it within the TTL window.

To pin a different component, set `[residency].pin` to the component name registered with the ledger. To pin nothing, set it to an empty string; the language organ then rotates like everything else.

## The work queue

Requests to load components go through a `WorkQueue` with two priority lanes: INTERACTIVE and BACKGROUND. Interactive requests (a user spoke and the entity needs STT) are dispatched before background requests (prewarming a component that might be needed soon). Background jobs can be preempted: if an interactive request needs memory that a running background load occupies, the background job receives a cancel signal, has a grace period to stop, and is forcibly interrupted if it does not.

The queue tracks deadline misses. An interactive job submitted with a deadline records an overshoot if it was not dispatched before that deadline. These misses surface in the residency event log.

## The fit report

`python -m kaine.setup.footprint` produces a fit report. It compares the enabled components' calibrated footprints against the host's budget and reports one of three results per domain:

- **co-resides**: every component fits within the budget at once. No swaps are needed.
- **multiplex**: the total exceeds the budget, but each component fits individually. The pinned component stays loaded, and the rest take turns.
- **does-not-fit**: a single component exceeds the budget on its own. The host cannot run that component at all, even alone.

When components must multiplex, the fit report names the pinned component and the list of multiplexed components, and describes the expected feel:

```
language stays loaded; 2 organ(s) take turns in 6.50 GiB; each turn that needs
a swapped-out organ waits for its load
```

The fit report also flags uncalibrated components. A component with no entry in the footprint catalogue gets an "uncalibrated" tag, and the fit report may say "cannot plan" if the missing figure makes the domain unplannable. Run `python -m kaine.setup.footprint` after changing backends to re-calibrate.

## The footprint catalogue

Calibrated component sizes live in `state/residency/footprints.json`. Each entry records the component name, backend, model ID, measured peak memory in bytes, host class (cpu, unified, or discrete), and the KAINE version that measured it. The catalogue is written by `python -m kaine.setup.footprint` and read at boot by the fit report and the rung selector.

The entry's identity is `(component, backend, model_id, host_class)`. A re-calibration with the same identity replaces the old entry. Entries for other host classes or backends are preserved, so moving the install between hosts does not lose the old measurements.

## Speech rungs

The audition and vocal modules each have a rung ladder: an ordered list of speech backends from heaviest to lightest.

For TTS (the vocal module):

1. Chatterbox (GPU service)
2. Kokoro English int8 (CPU, via sherpa-onnx)

For STT (the audition module):

1. Speaches faster-whisper medium.en (service)
2. Moonshine base English (CPU, via sherpa-onnx)
3. Moonshine tiny English (CPU, via sherpa-onnx)

At boot, `select_rung()` walks the ladder from heaviest to lightest and picks the heaviest installed rung that fits within the remaining budget. If no calibration data exists for a rung, it is treated as fitting (the system cannot prove it does not). If no rung is installed, the module's speech path is unavailable.

## llama-swap integration

When `[residency].llm_proxy = "llama-swap"`, the residency manager generates a proxy configuration for [llama-swap](https://github.com/mostlygeek/llama-swap) and writes it to `state/residency/llama-swap.yaml`. llama-swap sits between KAINE and one or more llama-server instances, starting and stopping them on demand and enforcing its own idle TTLs and exclusive groups.

The generated config contains the model alias (from `[language].model_id`), the command line to start the upstream llama-server (with the GGUF path, port, and flags), and the TTL for the language component. The proxy listens on the same port that `[language].chat_url` points at, so existing configuration and health checks work without changes.

This is for hosts where multiple LLM backends rotate through one GPU. On a host where only the language organ uses the GPU, native organ idle unload (`[language].model_server_sleep_idle_seconds`) is simpler. The default value of `[residency].llm_proxy` is `"none"`.

## What multiplexing feels like

When every component co-resides, there is nothing to notice: the entity thinks, listens, and speaks without delay.

When components must multiplex, a request that needs a non-resident backend hits a cold start. The steps are: queue the load, wait for any eviction to finish, load the backend, then serve the request. On an 8 GB unified-memory host with the language organ pinned, an STT request that arrives while the STT service is cold waits for Speaches or Moonshine to load before transcription begins. During that wait the entity's response to speech pauses.

The queue helps: interactive requests jump ahead of background loads, so a user's spoken input does not wait behind a speculative prewarm. And the TTL keeps recently used backends loaded for a window after their last use, so a second utterance within two minutes finds STT already resident.

On a 16 GiB or larger host, the fit report typically says "co-resides": the organ, STT, TTS, and vision encoder all fit at once, and no swaps happen.

## Honest limits

Residency does not make a small host fast. It makes a small host work at all, by fitting backends into available memory one or two at a time instead of refusing to start. The cost is latency spikes during swaps: a cold-start load of an STT or TTS backend takes hundreds of milliseconds to a few seconds depending on the backend and the storage speed.

Voice latency measurement (`kaine/residency/voice_latency.py`) tracks each voice turn's timing breakdown and separates warm-path turns (backend already loaded) from cold-path turns (a load happened mid-turn). If a rung keeps getting evicted and reloaded, `check_persistent_misses()` flags it as a persistent miss with the rung label and the count of consecutive cold turns.

Memory pressure monitoring (`PressureValve` in `kaine/residency/policy.py`) watches system memory and triggers additional evictions when available memory drops below the reserve. The pressure valve runs alongside the TTL sweep and is a safety net, not the primary eviction path.

## Frozen rungs in study mode

When `[experiment].deterministic` is true or a study config is active, the speech rungs selected at boot are frozen. A frozen rung that fails to load at runtime is recorded as a residency failure and an incident; no fallback rung is tried. The study gets a clear failure rather than a silent substitution of a different backend, because a different backend changes the experimental conditions.

Outside study mode, a failed load at the selected rung falls back to the next lighter rung in the ladder.

## Residency events

Every load, unload, eviction, downgrade, and queue drop is recorded as a `ResidencyEvent` in `kaine/residency/events.py`. Events carry a kind, the component name, a timestamp, and (depending on the kind) a reason, duration, freed bytes, or rung change. The event log is readable at runtime through `residency_events()` and as a snapshot of dicts through `residency_events_snapshot()`.

Event kinds:

- `load_start`, `load_end`: a component began and finished loading. `load_end` carries `duration_seconds`.
- `unload`: a component was unloaded. Carries a `reason` (explicit, TTL, pressure, or preempt).
- `evict`: a component was evicted under pressure. Carries `freed_bytes`.
- `downgrade`: a speech backend was replaced by a lighter rung. Carries `from_rung` and `to_rung`.
- `queue_drop`: a queued load was dropped before it started. Carries a `reason`.

## In-flight tracking

`InflightGate` (`kaine/residency/inflight.py`) counts work running in worker threads. When a component has in-flight requests, the ledger will not offer it as an eviction candidate. The gate issues tickets at admission and releases them when the work finishes, accounting for cancellation (a task that was cancelled before its worker thread started is released immediately; a task already running in a thread runs to completion and releases from that thread). `wait_idle()` returns once the in-flight count reaches zero, which the unload path uses to drain a component before teardown.

## Service controllers

External services (the language organ's model server, Speaches, Chatterbox) are started and stopped through `ServiceController` implementations in `kaine/residency/service_controller.py`. Each controller wraps a compose stop/start cycle (for containerized services) or the native organ lifecycle (for the model server), and exposes an async `health()` probe. A service flagged as `shared` (set by `[services.<name>].shared = true`) is never stopped or started by the residency manager, because another entity or process owns it.

## Configuration reference

Section `[residency]` in `config/kaine.toml`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `false` | Turn on the residency manager |
| `reserve_bytes` | int | `null` | Override the default memory reserve (the larger of 1 GiB and 10% of physical RAM) |
| `ttl_seconds` | int | `120` | Default idle TTL for all components |
| `ttl_overrides` | dict | `{}` | Per-component TTL overrides, keyed by component name |
| `pin` | string | `"language"` | Component to keep resident at all times; empty string to pin nothing |
| `prewarm` | list of strings | `[]` | Components to prewarm at boot at background priority |
| `llm_proxy` | string | `"none"` | `"none"` or `"llama-swap"` |
| `interactive_queue_max` | int | `16` | Capacity of the interactive priority lane |
| `background_queue_max` | int | `64` | Capacity of the background priority lane |
| `perception_queue_max` | int | `32` | Capacity of the perception queue |
| `perception_queue_max_age_s` | float | `10.0` | Maximum age in seconds of a perception queue entry before it is dropped |

## Key files

| File | Role |
|---|---|
| `kaine/residency/budget.py` | Memory budget derivation per domain (system, device, cgroup) |
| `kaine/residency/ledger.py` | Component state machine and budget enforcement |
| `kaine/residency/policy.py` | TTL sweep, pressure valve, prewarm |
| `kaine/residency/queue.py` | Work queue with priority lanes and preemption |
| `kaine/residency/router.py` | Bridges load/unload to the ledger and event log |
| `kaine/residency/fit.py` | Fit report: co-resides, multiplex, or does-not-fit |
| `kaine/residency/config.py` | Residency config keys and validation |
| `kaine/residency/events.py` | Residency event recording and snapshots |
| `kaine/residency/inflight.py` | In-flight request tracking for safe unload |
| `kaine/residency/service_controller.py` | Start/stop/health for model server, STT, TTS |
| `kaine/residency/llm_proxy.py` | llama-swap proxy config generation |
| `kaine/residency/catalogue.py` | Footprint catalogue (measured component sizes) |
| `kaine/residency/speech_rungs.py` | Speech backend rung ladders and selection |
| `kaine/residency/voice_latency.py` | Voice latency breakdown and persistent-miss detection |
| `kaine/residency/rung_freeze.py` | Frozen rungs for deterministic and study runs |
