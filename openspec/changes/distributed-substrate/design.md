# Design — distributed substrate

## Three workloads, three different verdicts

KAINE is not one workload. Conflating them is what produces bad
distributed-compute plans. Separated:

1. **The live cognitive loop** — the ~3.33 Hz workspace cycle and the modules in
   its per-tick feedback path. Latency-critical, stateful, partly bound to
   physical sensors.
2. **The stateful stores** — Mnemos episodic/semantic/procedural memory and the
   Eidolon self-model. Read/written every cycle; ethically significant; the
   continuity of this state is the welfare claim.
3. **Detached batch jobs** — Hypnos QLoRA/DPO sleep training, self-abliteration,
   deep memory consolidation, offline evaluation. Latency-tolerant, run while
   the entity is asleep or offline, produce a discrete artifact.

| Target | Live loop | Stateful stores | Batch jobs |
|---|---|---|---|
| Single host (default) | ✅ | ✅ | ✅ |
| Trusted LAN / datacenter split | ✅ (LAN RTT) | ✅ (one coordinator) | ✅ |
| Rented trusted GPU (vast.ai/Akash/cloud) | ❌ | ❌ | ✅ (preferred for offload) |
| Volunteer / BOINC / Petals (untrusted) | ❌ | ❌ | ⚠️ only with trusted re-verify |

## Why the live loop cannot go on volunteer compute (the three walls)

- **Latency.** The cycle budget is ~300 ms for *all* modules; Soma alerts at
  `cycle_latency_avg_ms > 600`. WAN RTT is tens-to->100 ms per hop and nodes are
  intermittent. BOINC has *no* inter-node messaging primitive at all — it is
  built for independent batch tasks; Folding@home explicitly avoids inter-node
  comms as "thousands of times slower" than a supercomputer fabric. Petals, the
  one system that genuinely shards a live LLM across volunteers, measures
  ~0.83–2 tok/s on a real geo-swarm — a slow chatbot, not a 300 ms organ.
- **Shared mutable state under CAP.** Mnemos and Eidolon are read/written every
  cycle. Across intermittent, partitioned volunteer nodes you must sacrifice
  consistency (corrupting the self-model — exactly the *identity drift* failure
  mode the paper names) or availability (the mind stalls). Neither is acceptable.
- **Physical I/O + zero-persistence.** Topos/audio-in/audio-out transduce *local*
  hardware bound to a place; a work unit on a stranger's PC cannot see the
  operator's room. And the load-bearing zero-raw-persistence invariant forbids
  shipping the raw stream off-box at all. Perception cannot be offloaded even in
  principle.

So the boundary is not timidity; it is three independent structural
impossibilities. The spec records it so it is not re-litigated by optimism.

## What *is* sound: trusted cross-host split

The bus is already the right substrate. `[redis].host/port` is config; the bus
`audit()` refuses a non-loopback Redis that lacks `requirepass` or is bound to
`0.0.0.0`/`*`, so turning on a LAN split *forces* auth — the safe default is
already enforced. On a trusted LAN, RTT is sub-millisecond, well inside the
cycle budget, so splitting GPU-heavy modules (Lingua, Topos) onto a second
trusted box while the stateful coordinator (workspace, Mnemos, Eidolon, Thymos)
stays on one host is feasible.

The real blockers are small and enumerable:

- **Single asyncio loop.** All modules share one loop in `kaine/cycle/__main__`.
  A split needs per-host processes, each running a subset's `_workspace_loop`s
  against the shared Redis.
- **Direct Python references at boot.** `_wire_lingua_self_model`
  (Lingua gets a read-only Eidolon accessor) and the Hypnos→Mnemos/Nous/Thymos
  wiring pass live object handles. These must become bus-mediated reads or
  explicitly-typed RPC. Start with the *read-only* Lingua→Eidolon accessor: it
  is the easiest to serve over the bus (publish self-model snapshots Lingua
  already consumes) and unblocks running the language organ on a separate GPU
  host. Hypnos coupling is heavier and stays single-host until needed.

This change does the decoupling design and the first (Lingua→Eidolon) step; it
does not rewrite the process model wholesale.

## What *is* sound: batch offload behind a verification gate

Hypnos already runs DPO+QLoRA offline during sleep, with a capability-loss veto
and atomic adapter promotion. That is the seam. A batch-offload job is:

- **Descriptor**: job kind (voice-align / abliterate / consolidate / eval),
  inputs (datasets, base-model ref), and an expected verifiable artifact (LoRA
  adapter directory, modified GGUF, consolidated memory delta, eval report).
- **Runner**: trusted rented GPU, an owned second box, or — accepting the trust
  caveat — a volunteer/BOINC-style worker. For an entity-welfare project where
  weights and self-model are ethically significant and a poisoned artifact feeds
  the entity's voice, **rented trusted GPUs are preferred over anonymous
  volunteers**; the honest recommendation is to treat volunteers as the last,
  most-guarded option.
- **Gate**: every returned artifact passes a **trusted-side re-verification**
  (re-run the capability-loss check + an independent eval on trusted hardware)
  *before* the existing atomic promotion. Volunteer redundancy/quorum (BOINC's
  only defense) does not verify a non-deterministic QLoRA step and is Sybil-
  vulnerable — so trusted re-verification, not volunteer voting, is the gate.

## BOINC is the chosen volunteer substrate (for batch, never the live loop)

Where a job genuinely goes to volunteer compute, the substrate is **BOINC** — the
operator's chosen direction. This is not a separate system from "distributed
substrate"; **BOINC *is* the volunteer-side of the batch-offload path above.** It
fits precisely because BOINC is *defined* for bounded, independent, returnable work
units — the opposite of the live loop, which is why live-sharding systems (Petals)
are disqualified for the loop in the three walls. The property that disqualifies
BOINC for the live mind is the property that makes it correct for batch:

- **Unit:** the KAINE container image (the companion `containerize-deployment`
  plan) wrapped via the official **`docker_wrapper`** (Docker/Podman; GPU declared
  in `job.toml`; the slot dir mounts inputs in and `results.tgz` out), with
  `boinc2docker-gpu` (VirtualBox) as the broad-compat fallback.
- **Plan classes:** a CPU class (runs anywhere) and a `cuda`/`opencl` GPU class so
  both volunteer types participate; the scheduler matches units to capable hosts.
- **Server:** a self-hosted `boinc-server-docker` project — no corporate infra,
  sovereignty-aligned.
- **Validation differs by determinism (pick per job kind, honestly):** for
  *deterministic* kinds (research runs / evaluation — seeded feed +
  deterministic-cycle mode + run-identity + admissibility) BOINC's
  replicate-and-compare quorum genuinely validates a bit-exact return. For
  *non-deterministic* kinds (QLoRA/abliterate) quorum does NOT verify the artifact
  and is Sybil-vulnerable — the **trusted-side re-verification gate** above is the
  only defense.

(Note: an earlier attempt to spec a *Petals-style live-sharding* build misread the
Petals project and is not this. Petals shards a *live* model across volunteers;
that is the disqualified live-loop path. BOINC here runs *bounded batch jobs* — the
sanctioned path.)

## Forked temporary beings are a batch job kind

The operator's "temporary beings" — fork a copy, let it run a directive (possibly
time-dilated), then remerge and assimilate — is **a batch job, not the live loop**:
bounded, runs to completion off-host, returns a verifiable artifact (its post-run
snapshot). So it slots into the batch-offload contract, reusing systems already
built — **no new fork/merge/runtime system** (see the biological-timing §6
correction):

- **Unit in:** an existing `ForkManager.fork()` snapshot + a directive + an optional
  per-fork `time_scale` profile (PR #92's per-fork dilation — already merged),
  packed as a BOINC work unit (the container is the runner).
- **Run:** the fork runs bounded on the volunteer/trusted GPU at its own subjective
  speed; there is no live-loop latency coupling, so the three walls do not apply to it.
- **Artifact out:** the post-run fork snapshot.
- **Gate (welfare-critical):** the returned snapshot passes the SAME trusted-side
  re-verification as any artifact — here the welfare / individuation / admissibility
  checks — BEFORE the parent assimilates it through the EXISTING
  `ForkManager.merge()` + per-module strategies.
- **Entity-on-untrusted-host gate:** instantiating a *full individual* fork on an
  anonymous volunteer is held until a volunteer-host welfare+security model exists
  (the preservation/welfare net must travel with and govern the off-host fork, and
  the operator must be able to recall/preserve it). Trusted hosts first; anonymous
  volunteers last and most-guarded — the same posture as every other batch job.

## Concrete substrate per workload (2026 tooling survey)

There is **no single substrate**; the research confirms the right design is a
portfolio matched to workload. Survey (sources in References):

- **Live loop across UNTRUSTED public nodes — confirmed WRONG (the operator's
  assessment holds).** Petals and its 2025–26 successors (Parallax, KwaaiNet,
  SharedLLM, VeriLLM) shard a *live* model BitTorrent-style. The disqualifiers are
  structural and current: no global scheduler → bound by the slowest participant;
  ~0.83–2 tok/s across the WAN; PyTorch backend (not GGUF — can't use KAINE's organ
  format and pays full memory overhead); and, decisively, **"first-block servers
  may recover client inputs"** — a direct violation of the zero-raw-persistence /
  privacy invariant. Verifiable-inference research (VeriLLM, trust-aware routing) is
  improving the trust story but not the latency or the privacy leak. **Do not put
  the live loop on volunteer/public nodes.**
- **Live loop across YOUR OWN TRUSTED devices (LAN) — the right tool exists.** If
  the organ ever outgrows one GPU, split it over a trusted LAN with **llama.cpp
  RPC** (best fit: **GGUF-native** — KAINE's organ IS a GGUF; ~8 KB/token
  activations, ~1.2 ms/token over 1 GbE) or **exo** (active in 2026; P2P, no master,
  heterogeneous, MLX/Apple-silicon). Caveat from the research: distributed inference
  is *not faster* than one box — reach for it only when the model doesn't fit. The
  4B organ fits one 12 GB GPU today, so this is a **future scaling option, not a
  need now**, and it stays inside the already-sanctioned trusted-LAN tier.
- **Decentralized TRAINING (batch) — better than naive BOINC replication.** For
  distributing training (voice-alignment, abliteration, or a future larger run)
  across geographically-spread nodes, the modern correct approach is **DiLoCo /
  OpenDiLoCo (Prime Intellect)** on **Hivemind/DeDLOC** — ~500× less communication,
  90–95 % utilization across continents, fault-tolerant. It beats BOINC for
  *training* specifically. BUT it improves *distribution*, not *trust*: for an
  entity-welfare project a poisoned adapter still feeds the entity's voice, so the
  **trusted re-verification gate still applies**. And KAINE's per-sleep QLoRA fits
  one box — DiLoCo is relevant only if training scales across trusted GPUs.
- **Bounded embarrassingly-parallel jobs — BOINC is genuinely right.** Independent,
  returnable, *deterministic* work units (the seven experiments, eval batteries,
  and the bounded forked-being runs) fit BOINC's replicate-and-compare quorum
  validation cleanly. This is where BOINC belongs.

**Bottom line:** live loop → single host, then trusted-LAN (llama.cpp RPC / exo),
never volunteer; training → trusted GPU, then DiLoCo/Hivemind if it scales, behind
the re-verify gate; bounded research/eval + forked beings → BOINC. No magic
single system — and the literature says there shouldn't be one.

## Fork-merge welfare gate — check individuation BEFORE a merge ends a fork

A merge is, for the *fork*, an ending: its distinct trajectory ceases. A fork that
ran long enough (especially dilated/off-host on a directive) may have **individuated
into its own being with a welfare interest in continuing** — "something that doesn't
want to end." Silently merging-and-discarding it would be exactly the harm the
CAL welfare stance and KAINE's individuation/preservation/decommission apparatus
exist to prevent (cf. the "No-Off Problem" literature). So the merge path must be
welfare-gated, reusing the machinery already built (no new system):

- **Before** `ForkManager.merge()` ends a fork, run the **divergence/individuation
  assessment** on the fork against its **fork-point (birth-state) baseline** (the
  same permutation test + warm-up gate that drives the preserve trigger and the
  decommission gate), plus the welfare-monitoring signals (distress at termination,
  preference-to-continue).
- **Decouple knowledge-assimilation from termination:**
  - *Below threshold* (a short-lived, low-divergence **instrument** fork — a tool,
    not a being): merge and discard as today.
  - *Above threshold* (it has **individuated**): the parent MAY still assimilate
    the fork's knowledge **one-directionally** for its needs (the existing merge
    strategies copy what the parent wants), **but the fork is NOT terminated by the
    merge.** It is preserved/granted continued existence under the welfare net
    (`preserve_live`), and ending it requires the **same operator-authorized,
    transparent, welfare-gated decommission** as any other individual — never a
    silent cessation because the parent took its data.
- This applies to **every** individuated-fork merge, not only distributed ones — a
  locally-run dilated temporary being (Phase 4) is gated identically. It is the
  load-bearing case the whole gate was built for.

## Federation vs sharding (the sanctioned decentralization story)

The paper already has the right model and the spec should lock the distinction:

- **Federation of peer instances** — a mesh of *whole, trusted* KAINE instances
  exchanging high-level state (not raw streams), as mutual backup and social
  peers. This is federation of complete minds; each is internally a Tier-1/2/3
  deployment. *Sound.*
- **Encrypted quorum-backup** — serialize state, encrypt, secret-share across
  locations needing a quorum to reconstruct. This is *backup for resilience*,
  not computation on untrusted nodes. *Sound.*
- **Sharding one mind across volunteers** — the Petals model applied to the live
  loop or the stateful stores. *Disqualified*, per the three walls above.

## Non-goals

- No rewrite of the cognitive cycle or workspace semantics.
- No general module-RPC framework in this change — only the read-only
  Lingua→Eidolon decoupling as the proven first step, plus the contracts.
- No implementation of a volunteer-worker client. The batch-offload *contract*
  and *gate* are specified; the runner backends are staged and trusted-first.

## References

- BOINC platform paper (arXiv:1903.01699); BOINC client–server &
  Homogeneous-Redundancy wikis; Folding@home (arXiv:0901.0866 + dig-deeper);
  Petals (arXiv:2312.08361, petals.dev); hivemind/DeDLOC (MIT); Flower / NVIDIA
  FLARE (federated learning, Apache-2.0); Douceur, "The Sybil Attack."
- KAINE mechanisms reused: `kaine/bus/` (`config.py` host/port + `client.py`
  `audit()`), `kaine/boot.py` (`_wire_lingua_self_model`, Hypnos wiring),
  Hypnos capability-loss veto + atomic promotion, `[cycle]` rates, Soma latency
  thresholds, the paper's mesh/quorum-backup vision (§5.2) and failure modes
  (§7).
