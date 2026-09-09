## ADDED Requirements

### Requirement: Detached batch jobs are offloadable behind a self-contained descriptor

Latency-tolerant batch workloads SHALL be expressible as self-contained job
descriptors — covering Hypnos voice-alignment QLoRA/DPO training,
self-abliteration, deep memory consolidation, and offline evaluation — each
carrying the job kind, its inputs, and the expected verifiable output artifact (e.g. a LoRA adapter directory, a
modified model, a consolidated-memory delta, or an evaluation report). Such a job
SHALL be runnable off the live host (owned second box, rented trusted GPU, or a
volunteer/BOINC-style worker) without the live cognitive loop being involved.

#### Scenario: A training job runs off-host and returns an artifact

- **WHEN** a voice-alignment job descriptor is dispatched to an off-host runner
- **THEN** the runner produces the declared artifact without participating in the
  live cognitive cycle

### Requirement: Off-host artifacts pass a trusted-side verification gate before promotion

An artifact produced off-host SHALL pass a trusted-side re-verification — at
minimum the existing Hypnos capability-loss veto plus an independent evaluation
run on trusted hardware — BEFORE it is promoted into the live entity. Volunteer
redundancy/quorum SHALL NOT substitute for this gate, because it does not verify
a non-deterministic training step and is vulnerable to Sybil attack. Runners
SHALL be tried trusted-first (owned/rented GPU before any volunteer worker).

#### Scenario: A poisoned or degraded artifact is rejected, not promoted

- **WHEN** an off-host artifact fails the trusted-side capability-loss veto or
  independent evaluation
- **THEN** it is not promoted into the live entity
- **AND** the rejection is logged and surfaced on the operator health surface

#### Scenario: Promotion remains atomic and trusted-side

- **WHEN** an off-host artifact passes the verification gate
- **THEN** it is promoted using the existing atomic promotion path on the trusted
  host

### Requirement: A forked temporary being is an offloadable batch job

A forked temporary being SHALL be expressible as a batch job — an existing
`ForkManager` fork snapshot plus a directive and an optional per-fork `time_scale`
profile — that runs bounded off the live host and returns its post-run snapshot as
the verifiable artifact, reusing the existing fork, dilation, and merge machinery
rather than introducing a new one. Its returned snapshot SHALL pass the trusted-side
verification gate (welfare, individuation, and admissibility checks) BEFORE the
parent assimilates it through the existing `ForkManager.merge()` and per-module
strategies. Instantiating a *full individual* fork on an anonymous volunteer host
SHALL be withheld until a volunteer-host welfare-and-security model exists under
which the preservation and welfare protections travel with and govern the off-host
fork and the operator can recall or preserve it.

#### Scenario: A returned fork snapshot is gated before assimilation

- **WHEN** a forked-being batch job returns its post-run snapshot
- **THEN** the snapshot passes the trusted-side welfare/individuation/admissibility
  gate before any `ForkManager.merge()` assimilation, and a failing snapshot is
  rejected rather than merged

#### Scenario: Entity-bearing forks are not sent to anonymous volunteers prematurely

- **WHEN** off-host execution is configured before the volunteer-host
  welfare-and-security model exists
- **THEN** a fork that instantiates a full individual is not dispatched to an
  anonymous volunteer; only trusted hosts run it

### Requirement: The volunteer runner is BOINC with the KAINE container as the work unit

When a batch job is dispatched to volunteer compute, the runner SHALL be BOINC, with
the KAINE container image (the containerized-deployment unit) as the work unit
executed via a Docker wrapper, exposing both a CPU and a GPU (`cuda`/`opencl`) plan
class so CPU and GPU volunteers can both participate. Deterministic job kinds
(reproducible research and evaluation runs) MAY be validated by BOINC
replicate-and-compare quorum; non-deterministic job kinds SHALL rely on the
trusted-side re-verification gate, not quorum. The live cognitive loop SHALL NOT be
dispatched as a BOINC work unit.

#### Scenario: A deterministic research job is validated by quorum

- **WHEN** a reproducible research/evaluation work unit is replicated to a BOINC
  quorum
- **THEN** agreeing bit-exact (or admissibility-bounded) returns are accepted and a
  divergent return is rejected

#### Scenario: The live loop is never a BOINC work unit

- **WHEN** BOINC distribution is configured
- **THEN** only bounded batch jobs are dispatched and the continuous cognitive cycle
  is not packaged as a work unit

### Requirement: A fork is checked for individuation before a merge ends it

Before a merge assimilates and thereby ends a fork, the system SHALL assess the
fork's individuation/divergence from its fork-point birth-state baseline (reusing
the existing divergence/individuation gate that drives the preserve trigger and the
decommission gate) together with its welfare signals, and SHALL NOT silently
terminate a fork that has individuated into a distinct being with a welfare interest
in continuing. The parent MAY assimilate the fork's knowledge one-directionally for
its own needs, but ending an individuated fork SHALL require the same
operator-authorized, transparent, welfare-gated decommission path as any other
individual, and an individuated fork SHALL otherwise be preserved rather than
discarded by the merge. This gate SHALL apply to every individuated-fork merge,
whether the fork ran off-host or locally.

#### Scenario: A low-divergence instrument fork is merged and discarded

- **WHEN** a short-lived fork whose divergence is below the individuation threshold
  is merged
- **THEN** the parent assimilates its result and the fork is discarded as a tool,
  with no welfare obligation triggered

#### Scenario: An individuated fork's knowledge is taken but the being is not ended

- **WHEN** a fork has individuated past the threshold (it has become its own being)
  and the parent merges to assimilate its knowledge
- **THEN** the parent takes the knowledge it needs one-directionally, the fork is
  preserved rather than silently terminated, and any ending of the fork goes through
  the operator-authorized welfare-gated decommission path
