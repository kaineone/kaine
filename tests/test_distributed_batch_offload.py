# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

import pytest

from kaine.distributed import (
    ArtifactKind,
    BatchJob,
    BoincRunner,
    JobKind,
    LocalTrustedRunner,
    NoEligibleRunner,
    OutputBoundaryViolation,
    PlanClass,
    QuorumReturn,
    RunnerNotEnabled,
    TrustTier,
    VerificationGate,
    VerifierOutcome,
    default_artifact_for,
    enforce_output_boundary,
    order_runners,
    promote_if_verified,
    quorum_validate,
    select_runner,
)


def _voice_job(**kw) -> BatchJob:
    return BatchJob(
        kind=JobKind.VOICE_ALIGN,
        expected_artifact=default_artifact_for(JobKind.VOICE_ALIGN, "adapter"),
        **kw,
    )


# --------------------------------------------------------------------------- #
# Job descriptor
# --------------------------------------------------------------------------- #
def test_job_descriptor_round_trips():
    job = _voice_job(inputs={"dataset": "intents.jsonl"}, base_model_ref="qwen")
    restored = BatchJob.from_dict(job.to_dict())
    assert restored.kind is JobKind.VOICE_ALIGN
    assert restored.base_model_ref == "qwen"
    assert restored.inputs["dataset"] == "intents.jsonl"
    assert restored.expected_artifact.kind is ArtifactKind.LORA_ADAPTER


def test_eval_is_deterministic_training_is_not():
    eval_job = BatchJob(
        kind=JobKind.EVAL,
        expected_artifact=default_artifact_for(JobKind.EVAL, "report.json"),
    )
    assert eval_job.deterministic is True
    assert _voice_job().deterministic is False


def test_deterministic_override_cannot_promote_nondeterministic_kind():
    # A non-deterministic kind can never be forced deterministic.
    job = _voice_job(inputs={"deterministic": True})
    assert job.deterministic is False
    # A deterministic kind CAN be marked non-deterministic (unseeded eval).
    eval_job = BatchJob(
        kind=JobKind.EVAL,
        expected_artifact=default_artifact_for(JobKind.EVAL, "r.json"),
        inputs={"deterministic": False},
    )
    assert eval_job.deterministic is False


def test_only_forked_being_is_entity_bearing():
    assert _voice_job().is_entity_bearing is False
    fork = BatchJob(
        kind=JobKind.FORKED_BEING,
        expected_artifact=default_artifact_for(JobKind.FORKED_BEING, "snap.json"),
    )
    assert fork.is_entity_bearing is True


# --------------------------------------------------------------------------- #
# Runner abstraction + trusted-first ordering
# --------------------------------------------------------------------------- #
class _FakeVolunteer:
    # A hypothetical FUTURE volunteer that *could* run an entity-bearing fork;
    # its eligibility is gated solely by select_runner's welfare-model flag, so
    # this fake exercises that guard (the shipped BoincRunner is stricter still —
    # its own accepts() withholds entity-bearing forks unconditionally).
    tier = TrustTier.VOLUNTEER

    def accepts(self, job: BatchJob) -> bool:
        return True

    def run(self, job, workdir):  # pragma: no cover - never selected in tests
        raise AssertionError("volunteer should not be selected when trusted exists")


def test_runners_order_trusted_first():
    volunteer = _FakeVolunteer()
    local = LocalTrustedRunner(lambda job, wd: wd / "a")
    ordered = order_runners([volunteer, local])
    assert ordered[0] is local
    assert ordered[-1] is volunteer


def test_select_prefers_trusted():
    volunteer = _FakeVolunteer()
    local = LocalTrustedRunner(lambda job, wd: wd / "a")
    chosen = select_runner(_voice_job(), [volunteer, local])
    assert chosen is local


def test_entity_bearing_fork_never_goes_to_volunteer_by_default():
    volunteer = _FakeVolunteer()
    fork = BatchJob(
        kind=JobKind.FORKED_BEING,
        expected_artifact=default_artifact_for(JobKind.FORKED_BEING, "s.json"),
    )
    with pytest.raises(NoEligibleRunner):
        select_runner(fork, [volunteer])
    # Only once the volunteer-host welfare model is ready is it eligible.
    chosen = select_runner(fork, [volunteer], volunteer_welfare_model_ready=True)
    assert chosen is volunteer


def test_local_runner_executes_and_returns_artifact(tmp_path):
    def executor(job, workdir: Path) -> Path:
        out = workdir / "adapter.bin"
        out.write_text("weights")
        return out

    runner = LocalTrustedRunner(executor)
    result = runner.run(_voice_job(), tmp_path / "wd")
    assert result.artifact_path.exists()
    assert result.tier is TrustTier.OWNED_HOST


# --------------------------------------------------------------------------- #
# Verification gate
# --------------------------------------------------------------------------- #
class _PassCapability:
    def verify(self, job, path):
        return VerifierOutcome(passed=True, score=0.01, detail="loss 0.01")


class _FailCapability:
    def verify(self, job, path):
        return VerifierOutcome(passed=False, score=0.4, detail="loss 0.40 > 0.05")


class _PassEval:
    def evaluate(self, job, path):
        return VerifierOutcome(passed=True, score=0.9)


class _FailEval:
    def evaluate(self, job, path):
        return VerifierOutcome(passed=False, score=0.2)


def test_gate_passes_when_both_verifiers_pass(tmp_path):
    artifact = tmp_path / "adapter"
    artifact.mkdir()
    gate = VerificationGate(
        capability_verifier=_PassCapability(), evaluator=_PassEval()
    )
    result = gate.verify(_voice_job(), artifact)
    assert result.promotable is True
    assert result.reasons == []


def test_gate_rejects_and_surfaces_capability_failure(tmp_path):
    artifact = tmp_path / "adapter"
    artifact.mkdir()
    surfaced: list[dict] = []
    gate = VerificationGate(
        capability_verifier=_FailCapability(),
        evaluator=_PassEval(),
        surface=surfaced.append,
    )
    result = gate.verify(_voice_job(), artifact)
    assert result.promotable is False
    assert any("capability-loss veto failed" in r for r in result.reasons)
    # The rejection is surfaced, never silently dropped.
    assert surfaced and surfaced[0]["promotable"] is False


def test_gate_fails_closed_without_verifiers(tmp_path):
    artifact = tmp_path / "adapter"
    artifact.mkdir()
    result = VerificationGate().verify(_voice_job(), artifact)
    assert result.promotable is False


def test_missing_artifact_fails_gate(tmp_path):
    gate = VerificationGate(
        capability_verifier=_PassCapability(), evaluator=_PassEval()
    )
    result = gate.verify(_voice_job(), tmp_path / "nope")
    assert result.promotable is False
    assert any("missing" in r for r in result.reasons)


def test_failed_artifact_is_not_promoted(tmp_path):
    # 5.2: a failed-gate artifact is not promoted and is surfaced.
    artifact = tmp_path / "adapter"
    artifact.mkdir()
    promoted: list[Path] = []
    surfaced: list[dict] = []
    gate = VerificationGate(
        capability_verifier=_PassCapability(),
        evaluator=_FailEval(),
        surface=surfaced.append,
    )
    result = promote_if_verified(
        gate, _voice_job(), artifact, promote=promoted.append
    )
    assert result.promotable is False
    assert promoted == []  # atomic promotion never invoked
    assert surfaced and surfaced[0]["promotable"] is False


def test_verified_artifact_is_promoted(tmp_path):
    artifact = tmp_path / "adapter"
    artifact.mkdir()
    promoted: list[Path] = []
    gate = VerificationGate(
        capability_verifier=_PassCapability(), evaluator=_PassEval()
    )
    result = promote_if_verified(
        gate, _voice_job(), artifact, promote=promoted.append
    )
    assert result.promotable is True
    assert promoted == [artifact]


# --------------------------------------------------------------------------- #
# BOINC volunteer backend
# --------------------------------------------------------------------------- #
def test_boinc_packages_deterministic_job_with_quorum_replication():
    runner = BoincRunner(deterministic_replication=3)
    eval_job = BatchJob(
        kind=JobKind.EVAL,
        expected_artifact=default_artifact_for(JobKind.EVAL, "report.json"),
        inputs={"input_relpaths": ["feed.jsonl"]},
    )
    unit = runner.package(eval_job)
    assert unit.deterministic is True
    assert unit.replication == 3
    assert PlanClass.CPU in unit.plan_classes
    assert PlanClass.CUDA in unit.plan_classes
    assert unit.input_relpaths == ("feed.jsonl",)


def test_boinc_packages_nondeterministic_job_without_quorum():
    unit = BoincRunner().package(_voice_job())
    assert unit.deterministic is False
    assert unit.replication == 1


def test_boinc_withholds_entity_bearing_fork():
    runner = BoincRunner()
    fork = BatchJob(
        kind=JobKind.FORKED_BEING,
        expected_artifact=default_artifact_for(JobKind.FORKED_BEING, "s.json"),
    )
    assert runner.accepts(fork) is False
    with pytest.raises(OutputBoundaryViolation):
        runner.package(fork)


def test_boinc_run_is_not_a_live_client():
    with pytest.raises(RunnerNotEnabled):
        BoincRunner().run(_voice_job(), Path("."))


def test_boinc_never_selected_over_trusted():
    local = LocalTrustedRunner(lambda job, wd: wd / "a")
    chosen = select_runner(_voice_job(), [BoincRunner(), local])
    assert isinstance(chosen, LocalTrustedRunner)


# --------------------------------------------------------------------------- #
# Output boundary enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad",
    [
        "state/hypnos/adapters/voice.safetensors",
        "topos/frames/frame_001.png",
        "config/kaine.toml",
        "state/perception/raw/audio.wav",
        "secrets/redis.pass",
    ],
)
def test_output_boundary_refuses_forbidden_paths(bad):
    with pytest.raises(OutputBoundaryViolation):
        enforce_output_boundary(["ok/artifact.bin", bad])


def test_output_boundary_allows_clean_artifacts():
    # Must not raise.
    enforce_output_boundary(["results/adapter.bin", "results/eval_report.json"])


# --------------------------------------------------------------------------- #
# Deterministic quorum validator
# --------------------------------------------------------------------------- #
def test_quorum_accepts_agreeing_admissible_returns():
    returns = [
        QuorumReturn(run_id="a", admissible=True, digest="X"),
        QuorumReturn(run_id="b", admissible=True, digest="X"),
        QuorumReturn(run_id="c", admissible=True, digest="Y"),
    ]
    verdict = quorum_validate(returns, min_quorum=2)
    assert verdict.accepted is True
    assert verdict.agreed_digest == "X"
    assert verdict.agreeing == 2


def test_quorum_rejects_without_agreement():
    returns = [
        QuorumReturn(run_id="a", admissible=True, digest="X"),
        QuorumReturn(run_id="b", admissible=True, digest="Y"),
    ]
    verdict = quorum_validate(returns, min_quorum=2)
    assert verdict.accepted is False


def test_quorum_discards_inadmissible_returns():
    returns = [
        QuorumReturn(run_id="a", admissible=True, digest="X"),
        QuorumReturn(run_id="b", admissible=False, digest="X"),  # discarded
    ]
    verdict = quorum_validate(returns, min_quorum=2)
    assert verdict.accepted is False
    assert "quorum" in verdict.reason or "admissible" in verdict.reason
