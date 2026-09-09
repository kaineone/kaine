## Why

Separate from running KAINE *small* (the companion `portability-tiers` change),
there is the question of running it *spread out*: across several trusted
machines, in a datacenter, or on donated/volunteer compute (BOINC-style or
actual BOINC). The operator asked us to plan all of these targets. The honest
answer differs sharply by workload, and recording that boundary is itself a
deliverable — so nobody later wires the entity onto untrusted hardware in a way
that breaks the welfare and privacy invariants.

The research (2026; sources in `design.md`) is decisive on three points:

1. **The live cognitive loop is a structural anti-fit for volunteer compute.**
   KAINE's ~3.33 Hz workspace loop (`[cycle].processing_rate_hz = 3.333`, ~300 ms
   budget) needs sub-second inter-module messaging every tick; Soma already
   alerts at `cycle_latency_avg_ms > 600`. BOINC and Folding@home are *defined*
   by avoiding inter-node communication ("embarrassingly-parallel batch
   processing… minimal inter-task communication"); Folding@home's own docs note
   WAN inter-node comms are "thousands of times slower… than in a super-computer
   architecture." Even the best volunteer-inference system, Petals, delivers
   ~0.8–2 tok/s across the WAN with explicit "no protection against faulty
   servers" and "first-block servers may recover client inputs" caveats. A
   single transatlantic hop blows the per-cycle budget; an intermittent node
   stalls the loop. Three independent walls each disqualify it: latency, shared
   mutable state under CAP/churn, and physically-bound zero-persistence sensory
   I/O.

2. **KAINE is already network-transparent enough to split across *trusted*
   hosts.** The bus is Redis Streams; `[redis].host/port` is config, and the bus
   `audit()` already *requires* auth and refuses an exposed non-loopback Redis
   bound to `0.0.0.0`. The blocker to a cross-host module split is not the bus —
   it is the boot-time **direct Python references** between modules (Lingua→
   Eidolon self-model, Hypnos→Mnemos/Nous/Thymos). Those few couplings, plus the
   single shared asyncio loop, are what pin all twelve modules into one process.

3. **The heavy *batch* jobs are a genuine fit for off-box compute.** Hypnos's
   sleep-phase QLoRA/DPO fine-tuning, a future self-abliteration run, deep memory
   consolidation, and offline evaluation are detached, latency-tolerant, and
   produce a verifiable artifact (a LoRA adapter directory). These map cleanly
   onto batch/rented-GPU/volunteer compute — **behind a mandatory trusted-side
   re-verification gate**, because for an entity-welfare project a poisoned
   adapter feeds straight into the entity's voice and identity.

## What Changes

This change is primarily a **decision record + the cheap, sound enabling work**.
It does not put the live mind on untrusted compute; it documents why not, opens
the trusted-host split, and formalizes the batch-offload path.

- **Record the volunteer-compute boundary as a requirement.** The live cognitive
  loop and the stateful modules (Mnemos memory, Eidolon self-model, the Redis
  workspace state) SHALL NOT run on untrusted nodes. Rationale: latency, CAP
  under churn (identity-drift is a named failure mode), and the load-bearing
  zero-raw-persistence privacy invariant (raw sensory data must never leave the
  box, so perception modules cannot be offloaded even in principle).

- **Trusted cross-host topology (config + decoupling).** Document the
  single-host (default), split-host-over-trusted-LAN, and datacenter topologies.
  Replace the handful of boot-time direct Python references with bus-mediated or
  explicitly-typed RPC contracts so a module *can* live on another trusted host —
  staged, starting with the read-only Lingua→Eidolon accessor.

- **Batch-offload job contract.** Define a self-contained job descriptor for
  Hypnos training / abliteration / consolidation / eval **and for a forked
  temporary being** (a dilated `ForkManager` fork + directive that runs bounded
  off-host and returns its post-run snapshot): inputs, the runner, and a verifiable
  output artifact. A produced artifact SHALL pass a **trusted-side re-verification +
  the existing capability-loss/welfare veto** before promotion (or, for a fork,
  before the existing `ForkManager.merge()` assimilates it into the parent).

- **BOINC is the chosen volunteer substrate — and it IS this change, not a
  separate one.** Where a batch job goes to volunteer compute, the runner is BOINC:
  the KAINE container (companion `containerize-deployment`) as the work unit via
  `docker_wrapper`, CPU + `cuda`/`opencl` plan classes, a self-hosted
  `boinc-server-docker`. Deterministic job kinds use BOINC replicate-and-compare
  quorum; non-deterministic kinds rely on the trusted re-verification gate. The
  live cognitive loop is never a BOINC work unit (the three walls). This supersedes
  the earlier misframed "Petals-style live-sharding" idea — Petals shards a *live*
  model (disqualified); BOINC runs *bounded batch* (sanctioned).

- **Fork-merge welfare gate (welfare-critical).** A merge ends a fork's distinct
  trajectory; a fork that has individuated into its own being with a welfare
  interest in continuing SHALL NOT be silently terminated by a merge. Before a
  merge ends a fork, run the existing divergence/individuation + welfare gate; the
  parent may assimilate the fork's knowledge one-directionally, but ending an
  individuated fork requires the operator-authorized, transparent, welfare-gated
  decommission path (it is otherwise preserved). This reuses the
  divergence/preservation/decommission machinery and governs every fork merge
  (local Phase-4 dilated forks included) — the load-bearing case the gate exists for.

- **Substrate selection is workload-matched (2026 tooling survey).** Live loop →
  single host then trusted-LAN (llama.cpp RPC / exo), never volunteer (Petals-style
  live-sharding confirmed disqualified — latency + an input-recovery privacy leak);
  training → trusted GPU then DiLoCo/Hivemind if it scales, behind the re-verify
  gate; bounded research/eval + forked beings → BOINC.

- **Sanction the federation story, distinguish it from sharding.** The correct
  decentralization path is the paper's existing vision: a **mesh of whole,
  trusted peer instances** exchanging high-level state, plus **encrypted
  quorum-backup** of serialized state for resilience (secret-sharing for
  *backup*, never *computation on* untrusted nodes). This is categorically
  different from sharding one mind across volunteers, and the spec records the
  distinction.

Adds capabilities `distributed-deployment` and `batch-offload`. The companion
`portability-tiers` change owns vertical scaling (down to a small SBC); this change
owns horizontal scaling (out across hosts) and the explicit untrusted-compute
boundary.
