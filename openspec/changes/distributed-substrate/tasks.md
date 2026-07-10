## 1. Decision record (the boundary)

- [x] 1.1 Record the untrusted-compute boundary as a spec requirement (live loop
      + stateful stores never on untrusted nodes; rationale: latency, CAP/churn
      identity-drift, zero-raw-persistence)
      — `specs/distributed-deployment/spec.md`: "The live cognitive loop and
      stateful stores never run on untrusted compute".
- [x] 1.2 Document the three-workload / four-target matrix in
      `docs/deployment-topologies.md` — added (workload × target matrix + three
      walls).
- [ ] 1.3 Paper §10 (Future Work) updated with the honest distributed assessment
      — DEFERRED: the paper source is not present in this public repo (no
      `paper/`/`*paper*` file, no §10/Future-Work source found under `docs/`), so
      it cannot be edited here. The honest assessment is captured in
      `docs/deployment-topologies.md`; the paper edit is an operator/private-repo
      follow-up.

## 2. Trusted cross-host split (staged decoupling)

- [x] 2.1 Confirm + document that a LAN bus split forces auth via the existing
      `audit()` (non-loopback Redis must have `requirepass`, not bound to `*`)
      — verified `kaine/bus/client.py::AsyncBus.audit` (raises `BusSecurityError`
      on wildcard bind AND on missing `requirepass`); documented in the topology doc.
- [x] 2.2 Replace the read-only Lingua→Eidolon Python reference
      (`_wire_lingua_self_model`) with a bus-mediated self-model snapshot Lingua
      already consumes, so Lingua can run on a separate trusted GPU host
      — `kaine/modules/eidolon/module.py::Eidolon._publish_self_model` (+ boot
      publish) → `eidolon.out`; `kaine/modules/lingua/module.py::Lingua.
      _self_model_cache_loop` / `_self_model`; `kaine/boot.py::_wire_lingua_self_model`
      no longer passes a live handle.
- [x] 2.3 Document the per-host process model (subset of modules per process,
      shared Redis) without rewriting the single-host default
      — `docs/deployment-topologies.md` "Per-host process model".
- [x] 2.4 Leave Hypnos→Mnemos/Nous/Thymos coupling single-host; note it as the
      next decoupling target — documented (topology doc + `_wire_lingua_self_model`
      docstring); no code moves it.

## 3. Batch-offload contract + gate

- [x] 3.1 Define the job descriptor (kind, inputs, expected verifiable artifact)
      for voice-align / abliterate / consolidate / eval
      — `kaine/distributed/job.py::BatchJob` / `JobKind` / `ExpectedArtifact`.
- [x] 3.2 Trusted-side re-verification gate reusing the Hypnos capability-loss
      veto + an independent eval, run BEFORE atomic promotion
      — `kaine/distributed/gate.py::VerificationGate` + `promote_if_verified`.
- [x] 3.3 Runner abstraction with trusted-first ordering (owned/rented GPU →
      volunteer last, most-guarded); no volunteer client implemented here
      — `kaine/distributed/runner.py::TrustTier` / `order_runners` / `select_runner`
      / `LocalTrustedRunner`.
- [x] 3.4 Log/surface any artifact that fails the gate (never silently promote)
      — `VerificationGate` logs + `surface` callback on every verdict; see
      `test_gate_rejects_and_surfaces_capability_failure`.
- [x] 3.5 Add the **forked-temporary-being** job kind: descriptor = existing
      `ForkManager.fork()` snapshot + directive + optional per-fork `time_scale`
      (PR #92); artifact = post-run snapshot; gate = welfare/individuation/
      admissibility re-verify BEFORE the existing `ForkManager.merge()` assimilates
      it. Reuse the fork/dilation/merge systems — add NO new ones.
      — `kaine/distributed/fork_being.py::build_forked_being_job` /
      `forked_being_gate` (reuses `lifecycle.timing_profile` + the fork-merge gate).

## 3b. BOINC volunteer runner (the chosen substrate; depends on containerize-deployment)

- [x] 3b.1 BOINC runner backend behind the §3.3 runner abstraction: KAINE container
      as the work unit via `docker_wrapper` (Docker/Podman; GPU via `job.toml`;
      `boinc2docker-gpu` fallback); CPU + `cuda`/`opencl` plan classes.
      — `kaine/distributed/boinc.py::BoincRunner` / `WorkUnit` / `PlanClass`
      (CPU + CUDA + OPENCL). Contract-level: `run()` raises `RunnerNotEnabled`;
      live `docker_wrapper` dispatch is the B1 phase (depends on
      `containerize-deployment`), per the design non-goal ("no volunteer client").
- [ ] 3b.2 Self-hosted `boinc-server-docker` project (sovereign infra) + a
      deterministic validator (replicate-and-compare quorum reusing run-identity +
      admissibility) for the deterministic job kinds; non-deterministic kinds stay
      on the trusted re-verify gate.
      — PARTIAL/DEFERRED: the deterministic validator IS implemented
      (`kaine/distributed/boinc.py::quorum_validate` + `QuorumReturn`, discards
      inadmissible returns then requires an agreeing quorum). Standing up the
      self-hosted `boinc-server-docker` project is operator-provisioned sovereign
      infra (documented as B1 in the topology doc) and depends on
      `containerize-deployment`; left unchecked pending that.
- [x] 3b.3 Enforce zero-raw-sense-data + no private voices/adapters/operator-config
      at the work-unit output boundary; entity-bearing forks withheld until the
      volunteer-host welfare+security model exists.
      — `kaine/distributed/boinc.py::enforce_output_boundary` (refuses raw sense /
      adapters / `kaine.toml` / secrets); `BoincRunner.accepts` withholds
      entity-bearing forks; `runner.select_runner` gates them on the welfare flag.
- [x] 3b.4 Phasing note in the doc: B0 containerize → B1 BOINC harness → B2
      non-entity research/training units → B3 (gated) entity-bearing forked beings.
      — `docs/deployment-topologies.md` "BOINC phasing".

## 3c. Fork-merge welfare gate (welfare-critical; reuses divergence/preservation/decommission)

- [x] 3c.1 Before `ForkManager.merge()` ends a fork, run the existing
      divergence/individuation assessment (fork vs fork-point birth-state baseline +
      warm-up gate) + welfare signals. Below threshold → merge+discard (instrument);
      above → individuated being.
      — `kaine/lifecycle/fork_merge_gate.py::gated_merge` (+ `assess_fork` reusing
      `lifecycle.divergence.assess_divergence`) / `WelfareSignals`.
- [x] 3c.2 For an individuated fork: assimilate knowledge one-directionally into the
      parent (existing merge strategies) but DO NOT terminate the fork via the merge;
      route it to `preserve_live` + require the operator-authorized welfare-gated
      decommission to end it. Applies to local (Phase-4) AND off-host forks.
      — `gated_merge` individuated branch: parent merges (assimilates) but the fork
      is `fork_preserved=True`, `requires_operator_decommission=True`, never
      terminated; `preserve_fn` hook wires `ForkManager.preserve_live`.
- [x] 3c.3 Surface the pre-merge divergence verdict + the fork's fate (discarded vs
      preserved) on the operator health/welfare surface; log it.
      — `gated_merge` `surface` callback (emits `ForkMergeVerdict.to_dict`) + logs;
      see `test_individuated_fork_is_preserved_not_terminated`.
- [ ] 3c.4 (Consider) lift 3c into a lifecycle-wide requirement on the
      entity-decommission capability so it governs ALL fork merges canonically, not
      only the distributed ones.
      — PARTIAL/DEFERRED: the gate is implemented at the lifecycle level
      (`kaine/lifecycle/fork_merge_gate.py`, capability-neutral, governs every
      merge — local and off-host). Formalizing it as an ADDED requirement on the
      `entity-decommission` capability spec is a separate spec edit (a "consider"
      item, outside this change's two spec deltas); left as a follow-up.

## 3d. Concrete substrate selection (2026 tooling)

- [x] 3d.1 Record the workload→tool portfolio: live loop = single host → trusted-LAN
      (llama.cpp RPC GGUF-native / exo), never volunteer; training = trusted GPU →
      DiLoCo/Hivemind if it scales, behind the re-verify gate; bounded research/eval
      + forked beings = BOINC. Petals-style live-sharding documented as disqualified
      (latency + input-recovery privacy leak).
      — `docs/deployment-topologies.md` "Concrete substrate per workload".

## 4. Federation vs sharding (lock the distinction)

- [x] 4.1 Spec the sanctioned decentralization paths: peer-instance federation
      (whole trusted minds, high-level state) + encrypted quorum-backup
      — `specs/distributed-deployment/spec.md`: "Sanctioned decentralization is
      federation and encrypted backup, not sharding".
- [x] 4.2 Spec that sharding one mind (live loop / stateful stores) across
      untrusted nodes is disallowed, cross-referencing 1.1
      — same requirement ("Sharding a single mind across untrusted nodes SHALL
      remain disallowed per the boundary requirement above").

## 5. Validation

- [x] 5.1 Lingua boots against a bus-mediated (not in-process) self-model snapshot
      — `tests/test_lingua_bus_self_model.py`.
- [x] 5.2 A failed-gate artifact is not promoted and is surfaced
      — `tests/test_distributed_batch_offload.py::test_failed_artifact_is_not_promoted`.
- [x] 5.3 `openspec validate distributed-substrate --strict` — passes ("Change
      'distributed-substrate' is valid").
