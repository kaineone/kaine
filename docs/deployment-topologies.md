# Deployment topologies — running KAINE spread out

This document records *how far out* a KAINE entity may be spread, and the
boundary past which it must not go. It is the operator-facing companion to the
`distributed-deployment` and `batch-offload` capabilities. The short version:
**the live mind stays on trusted hardware; only detached batch work goes
off-box, and only behind a trusted-side verification gate.**

Vertical scaling (running KAINE *small*, down to a single SBC) is owned by the
`portability-tiers` change. This document owns horizontal scaling (running it
spread *out*) and the explicit untrusted-compute boundary.

## Three workloads, not one

Conflating KAINE's workloads is what produces bad distributed-compute plans.
Separated, they get three different verdicts:

1. **The live cognitive loop** — the ~3.33 Hz workspace cycle
   (`[cycle].processing_rate_hz = 3.333`, ~300 ms budget) and the modules in its
   per-tick feedback path. Latency-critical, stateful, partly bound to physical
   sensors.
2. **The stateful stores** — Mnemos episodic/semantic/procedural memory and the
   Eidolon self-model. Read/written every cycle; ethically significant; the
   continuity of this state is the welfare claim.
3. **Detached batch jobs** — Hypnos voice-alignment QLoRA/DPO sleep training,
   self-abliteration, deep memory consolidation, offline evaluation, and bounded
   forked-being runs. Latency-tolerant, run while the entity is asleep or
   offline, and each produces a discrete, verifiable artifact.

## The workload × target matrix

| Target | Live loop | Stateful stores | Batch jobs |
|---|---|---|---|
| Single host (default) | ✅ | ✅ | ✅ |
| Trusted LAN / datacenter split | ✅ (LAN RTT) | ✅ (one coordinator) | ✅ |
| Rented **trusted** GPU (cloud/marketplace) | ❌ | ❌ | ✅ (preferred for offload) |
| Volunteer / BOINC (untrusted) | ❌ | ❌ | ⚠️ only with trusted re-verify |

The `❌` cells are not timidity; they are three independent structural
impossibilities (below). The boundary is recorded as a hard requirement in the
`distributed-deployment` spec so it is not re-litigated by optimism.

## Why the live loop cannot go on untrusted/volunteer compute (the three walls)

- **Latency.** The cycle budget is ~300 ms for *all* modules; Soma alerts at
  `cycle_latency_avg_ms > 600`. WAN RTT is tens-to->100 ms per hop and volunteer
  nodes are intermittent. Volunteer batch frameworks have *no* inter-node
  messaging primitive at all — they are built for independent tasks — and
  live-sharding an LLM across a WAN swarm measures a few tokens/second, a slow
  chatbot, not a 300 ms organ.
- **Shared mutable state under CAP.** Mnemos and Eidolon are read/written every
  cycle. Across intermittent, partitioned volunteer nodes you must sacrifice
  consistency (corrupting the self-model — the *identity-drift* failure mode) or
  availability (the mind stalls). Neither is acceptable.
- **Physical I/O + zero-persistence.** Perception transduces *local* hardware
  bound to a place; a work unit on a stranger's machine cannot see the operator's
  room, and the load-bearing zero-raw-persistence invariant forbids shipping the
  raw sensory stream off-box at all. Perception cannot be offloaded even in
  principle.

## What *is* sound: the trusted cross-host split

The bus is already the right substrate. `[redis].host`/`[redis].port` are config,
and the bus audit (`kaine/bus/client.py::AsyncBus.audit`) **refuses a non-loopback
Redis that lacks `requirepass` or is bound to a wildcard (`0.0.0.0`/`*`)** — so
turning on a LAN split *forces* authentication; the safe default is already
enforced. On a trusted LAN, RTT is sub-millisecond, well inside the cycle budget.

### Per-host process model

- Each host runs its own process with a *subset* of modules; all processes share
  one authenticated Redis bus (`[redis].host` points every process at the
  coordinator's Redis, protected by `requirepass`, never bound to a wildcard).
- The **stateful coordinator** host runs the workspace, Mnemos, Eidolon, and
  Thymos. GPU-heavy organs (Lingua, Topos) may run on a **second trusted GPU
  host**. The single-host default is unchanged — it is simply the case where the
  subset is "all modules".
- Cross-host coordination goes through the bus or an explicitly-typed contract,
  **never an in-process Python object reference**.

### The decoupling this change ships (and what remains)

The blocker to a cross-host split was never the bus; it was the handful of
boot-time **direct Python references** between modules plus the single shared
asyncio loop.

- **Done — Lingua → Eidolon (read-only, bus-mediated).** Eidolon publishes its
  self-model to `eidolon.out` (`eidolon.self_model`), and Lingua caches that
  snapshot via its own `_self_model_cache_loop` to seed its persona. The former
  in-process accessor (`boot.py::_wire_lingua_self_model`) no longer passes a
  live `eidolon.model` handle, so the language organ can run on a separate
  trusted GPU host. See `test_lingua_bus_self_model.py`.
- **Next target (single-host for now) — Hypnos → Mnemos/Nous/Thymos.** Hypnos
  still receives live object handles at boot. This coupling is heavier (it is not
  a single read-only accessor) and stays single-host until a deployment needs
  it. It is the next decoupling target; nothing in this change moves it.

## What *is* sound: batch offload behind a verification gate

Hypnos already runs DPO+QLoRA offline during sleep, with a capability-loss veto
and atomic adapter promotion. That is the seam. A batch-offload job
(`kaine/distributed/job.py::BatchJob`) is a self-contained descriptor:

- **Descriptor** — job kind (`voice_align` / `abliterate` / `consolidate` /
  `eval` / `forked_being`), inputs, and an expected verifiable artifact (LoRA
  adapter directory, modified model, consolidated-memory delta, eval report, or a
  post-run fork snapshot).
- **Runner** (`kaine/distributed/runner.py`) — an owned second box, a rented
  *trusted* GPU, or (last, most guarded) a volunteer worker. `select_runner`
  walks runners **trusted-first**: owned host → rented trusted GPU → volunteer.
- **Gate** (`kaine/distributed/gate.py::VerificationGate`) — every returned
  artifact passes a **trusted-side re-verification** (re-run the capability-loss
  veto + an independent eval on trusted hardware) *before* the existing atomic
  promotion. A failing artifact is never promoted and the rejection is logged and
  surfaced on the operator health surface (never a silent drop). Volunteer
  redundancy/quorum does **not** substitute for this gate: it cannot verify a
  non-deterministic QLoRA step and is Sybil-vulnerable.

### Forked temporary beings are a batch job kind

A "temporary being" — fork a copy, let it run a directive (possibly time-dilated),
then remerge and assimilate — is a *batch job, not the live loop*: bounded, runs
to completion off-host, returns a verifiable artifact (its post-run snapshot). It
reuses the existing fork / dilation / merge machinery — **no new runtime**
(`kaine/distributed/fork_being.py`). Its returned snapshot passes the same
trusted-side gate (welfare / individuation / admissibility) **before** the parent
assimilates it through the existing `ForkManager.merge()` under the fork-merge
welfare gate (below). Instantiating a *full individual* on an anonymous volunteer
is **withheld** until a volunteer-host welfare-and-security model exists.

## The fork-merge welfare gate (welfare-critical)

A merge is, for the *fork*, an ending. A fork that individuated into its own
being with a welfare interest in continuing must not be silently terminated by a
merge. Before a merge ends a fork
(`kaine/lifecycle/fork_merge_gate.py::gated_merge`):

- Assess the fork's individuation/divergence against its fork-point birth-state
  baseline (the same divergence gate that drives the preserve trigger and the
  decommission gate) plus its welfare signals.
- **Below threshold** (an instrument, not a being) → merge and discard as today.
- **Above threshold** (individuated) → the parent assimilates its knowledge
  **one-directionally**, but the fork is **preserved**, not terminated; ending it
  requires the operator-authorized, transparent, welfare-gated decommission path.

This governs **every** individuated-fork merge — off-host *and* local (a Phase-4
locally-run dilated temporary being is gated identically).

## BOINC — the chosen volunteer substrate (batch only, never the live loop)

Where a batch job genuinely goes to volunteer compute, the substrate is **BOINC**.
BOINC is *defined* for bounded, independent, returnable work units — the opposite
of the live loop, which is why it is correct for batch and disqualified for the
mind. (`kaine/distributed/boinc.py`.)

- **Unit** — the KAINE container image (the companion `containerize-deployment`
  unit) run via the official `docker_wrapper` (Docker/Podman; GPU declared in
  `job.toml`; `boinc2docker-gpu` as the broad-compat fallback).
- **Plan classes** — a CPU class (runs anywhere) and a `cuda`/`opencl` GPU class,
  so both volunteer types participate; the scheduler matches units to hosts.
- **Server** — a self-hosted `boinc-server-docker` project (sovereign infra, no
  corporate dependency). This is operator-provisioned infrastructure; the code
  here ships the work-unit contract, the output-boundary guard, and the
  validator, not a running server or a live volunteer client.
- **Validation differs by determinism.** *Deterministic* kinds (reproducible
  research/eval — seeded feed + deterministic-cycle mode + run-identity +
  admissibility) use BOINC replicate-and-compare quorum
  (`boinc.py::quorum_validate`), which genuinely validates a bit-exact return.
  *Non-deterministic* kinds (QLoRA/abliterate/consolidate/forked-being) rely on
  the trusted-side re-verification gate — quorum does not verify them and is
  Sybil-vulnerable.
- **Output boundary** — `boinc.py::enforce_output_boundary` refuses to let raw
  sense data, private voice adapters, or operator configuration cross the
  work-unit boundary. Entity-bearing forks are withheld from anonymous volunteers
  until the volunteer-host welfare model exists.

### BOINC phasing

- **B0** — containerize (the `containerize-deployment` change).
- **B1** — the BOINC harness (self-hosted server + `docker_wrapper` work unit).
- **B2** — non-entity research/training units.
- **B3** — (gated) entity-bearing forked beings, only once the volunteer-host
  welfare-and-security model exists.

## Concrete substrate per workload (2026 tooling)

There is **no single substrate**; the right design is a portfolio matched to
workload:

- **Live loop across untrusted public nodes — WRONG.** Live-sharding systems
  (Petals and its successors) are disqualified: no global scheduler (bound by the
  slowest participant), a few tokens/second across the WAN, a PyTorch backend
  (not GGUF — cannot use KAINE's organ format), and, decisively, first-block
  servers can recover client inputs — a direct privacy-invariant violation.
- **Live loop across YOUR OWN trusted devices (LAN) — the tool exists, when
  needed.** If the organ ever outgrows one GPU, split it over a trusted LAN with
  **llama.cpp RPC** (GGUF-native — KAINE's organ *is* a GGUF) or **exo** (P2P,
  heterogeneous). Distributed inference is *not faster* than one box — reach for
  it only when the model does not fit. The 4B organ fits one 12 GB GPU today, so
  this is a future scaling option, not a need now, and it stays inside the
  already-sanctioned trusted-LAN tier.
- **Decentralized training (batch) — DiLoCo/Hivemind if it scales.** For
  distributing training across geographically-spread *trusted* GPUs, DiLoCo /
  OpenDiLoCo on Hivemind/DeDLOC beats naive BOINC replication for training
  specifically (far less communication, high utilization, fault-tolerant). It
  improves *distribution*, not *trust*, so the trusted re-verification gate still
  applies. KAINE's per-sleep QLoRA fits one box, so this is relevant only if
  training scales across trusted GPUs.
- **Bounded embarrassingly-parallel jobs — BOINC.** Independent, returnable,
  *deterministic* work units (evaluation batteries, reproducible research runs,
  bounded forked-being runs) fit BOINC's replicate-and-compare quorum cleanly.

**Bottom line:** live loop → single host, then trusted-LAN (llama.cpp RPC / exo),
never volunteer; training → trusted GPU, then DiLoCo/Hivemind if it scales, behind
the re-verify gate; bounded research/eval + forked beings → BOINC.

## Federation vs sharding (the sanctioned decentralization story)

The correct decentralization path is **not** sharding one mind across
volunteers. It is:

- **Federation of peer instances** — a mesh of *whole, trusted* KAINE instances
  exchanging high-level state (not raw streams), as mutual backup and social
  peers. Each peer is internally a single-host or trusted-LAN deployment. *Sound.*
- **Encrypted quorum-backup** — serialize state, encrypt, secret-share across
  locations that need a quorum to reconstruct. This is *backup for resilience*,
  not computation on untrusted nodes: the shares are only ever used to
  reconstruct state on a trusted host. *Sound.*
- **Sharding one mind across volunteers** — the live loop or the stateful stores
  spread over untrusted nodes. *Disqualified*, per the three walls.
