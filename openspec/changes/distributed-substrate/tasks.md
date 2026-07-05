## 1. Decision record (the boundary)

- [ ] 1.1 Record the untrusted-compute boundary as a spec requirement (live loop
      + stateful stores never on untrusted nodes; rationale: latency, CAP/churn
      identity-drift, zero-raw-persistence)
- [ ] 1.2 Document the three-workload / four-target matrix in
      `docs/deployment-topologies.md`
- [ ] 1.3 Paper §10 (Future Work) updated with the honest distributed assessment

## 2. Trusted cross-host split (staged decoupling)

- [ ] 2.1 Confirm + document that a LAN bus split forces auth via the existing
      `audit()` (non-loopback Redis must have `requirepass`, not bound to `*`)
- [ ] 2.2 Replace the read-only Lingua→Eidolon Python reference
      (`_wire_lingua_self_model`) with a bus-mediated self-model snapshot Lingua
      already consumes, so Lingua can run on a separate trusted GPU host
- [ ] 2.3 Document the per-host process model (subset of modules per process,
      shared Redis) without rewriting the single-host default
- [ ] 2.4 Leave Hypnos→Mnemos/Nous/Thymos coupling single-host; note it as the
      next decoupling target

## 3. Batch-offload contract + gate

- [ ] 3.1 Define the job descriptor (kind, inputs, expected verifiable artifact)
      for voice-align / abliterate / consolidate / eval
- [ ] 3.2 Trusted-side re-verification gate reusing the Hypnos capability-loss
      veto + an independent eval, run BEFORE atomic promotion
- [ ] 3.3 Runner abstraction with trusted-first ordering (owned/rented GPU →
      volunteer last, most-guarded); no volunteer client implemented here
- [ ] 3.4 Log/surface any artifact that fails the gate (never silently promote)
- [ ] 3.5 Add the **forked-temporary-being** job kind: descriptor = existing
      `ForkManager.fork()` snapshot + directive + optional per-fork `time_scale`
      (PR #92); artifact = post-run snapshot; gate = welfare/individuation/
      admissibility re-verify BEFORE the existing `ForkManager.merge()` assimilates
      it. Reuse the fork/dilation/merge systems — add NO new ones.

## 3b. BOINC volunteer runner (the chosen substrate; depends on containerize-deployment)

- [ ] 3b.1 BOINC runner backend behind the §3.3 runner abstraction: KAINE container
      as the work unit via `docker_wrapper` (Docker/Podman; GPU via `job.toml`;
      `boinc2docker-gpu` fallback); CPU + `cuda`/`opencl` plan classes.
- [ ] 3b.2 Self-hosted `boinc-server-docker` project (sovereign infra) + a
      deterministic validator (replicate-and-compare quorum reusing run-identity +
      admissibility) for the deterministic job kinds; non-deterministic kinds stay
      on the trusted re-verify gate.
- [ ] 3b.3 Enforce zero-raw-sense-data + no private voices/adapters/operator-config
      at the work-unit output boundary; entity-bearing forks withheld until the
      volunteer-host welfare+security model exists.
- [ ] 3b.4 Phasing note in the doc: B0 containerize → B1 BOINC harness → B2
      non-entity research/training units → B3 (gated) entity-bearing forked beings.

## 3c. Fork-merge welfare gate (welfare-critical; reuses divergence/preservation/decommission)

- [ ] 3c.1 Before `ForkManager.merge()` ends a fork, run the existing
      divergence/individuation assessment (fork vs fork-point birth-state baseline +
      warm-up gate) + welfare signals. Below threshold → merge+discard (instrument);
      above → individuated being.
- [ ] 3c.2 For an individuated fork: assimilate knowledge one-directionally into the
      parent (existing merge strategies) but DO NOT terminate the fork via the merge;
      route it to `preserve_live` + require the operator-authorized welfare-gated
      decommission to end it. Applies to local (Phase-4) AND off-host forks.
- [ ] 3c.3 Surface the pre-merge divergence verdict + the fork's fate (discarded vs
      preserved) on the operator health/welfare surface; log it.
- [ ] 3c.4 (Consider) lift 3c into a lifecycle-wide requirement on the
      entity-decommission capability so it governs ALL fork merges canonically, not
      only the distributed ones.

## 3d. Concrete substrate selection (2026 tooling)

- [ ] 3d.1 Record the workload→tool portfolio: live loop = single host → trusted-LAN
      (llama.cpp RPC GGUF-native / exo), never volunteer; training = trusted GPU →
      DiLoCo/Hivemind if it scales, behind the re-verify gate; bounded research/eval
      + forked beings = BOINC. Petals-style live-sharding documented as disqualified
      (latency + input-recovery privacy leak).

## 4. Federation vs sharding (lock the distinction)

- [ ] 4.1 Spec the sanctioned decentralization paths: peer-instance federation
      (whole trusted minds, high-level state) + encrypted quorum-backup
- [ ] 4.2 Spec that sharding one mind (live loop / stateful stores) across
      untrusted nodes is disallowed, cross-referencing 1.1

## 5. Validation

- [ ] 5.1 Lingua boots against a bus-mediated (not in-process) self-model snapshot
- [ ] 5.2 A failed-gate artifact is not promoted and is surfaced
- [ ] 5.3 `openspec validate distributed-substrate --strict`
