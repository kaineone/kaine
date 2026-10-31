# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The TIES/DARE merge runs in a child process, never in the caller.

Covers the parent side (``ChildMergeRunner`` and ``TiesDareAdapterMerger``)
with an injected fake launcher, the worker's job/result files, and one real
merge of two tiny LoRA adapters through a real child process (skipped where
peft is absent).
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from kaine.lifecycle import adapter_merge as am
from kaine.lifecycle.adapter_merge import (
    ChildMergeRunner,
    MergeWorkerError,
    TiesDareAdapterMerger,
    TiesDareMergeConfig,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# fake child
# --------------------------------------------------------------------------- #
def _read_job(argv: list[str]) -> tuple[Path, dict[str, Any]]:
    job_dir = Path(argv[-1])
    return job_dir, json.loads((job_dir / "job.json").read_text())


def _stage_adapter(job: dict[str, Any]) -> None:
    staging = Path(job["staging_dir"])
    staging.mkdir(parents=True)
    (staging / "adapter_config.json").write_text("{}")
    (staging / "adapter_model.safetensors").write_text("x")


def _write_result(job_dir: Path, result: Any) -> None:
    (job_dir / "result.json").write_text(
        result if isinstance(result, str) else json.dumps(result)
    )


def _evidence(**over: Any) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "abliteration_passed": True,
        "abliteration_probes_scored": 4,
        "capability_score_parents": [0.8, 0.6],
        "capability_score_merged": 0.7,
        "capability_loss": 0.0,
    }
    ev.update(over)
    return ev


def _ok_result(job: dict[str, Any], **evidence_over: Any) -> dict[str, Any]:
    return {
        "schema_version": am.MERGE_SCHEMA_VERSION,
        "ok": True,
        "rejection": None,
        "merged_dir": job["staging_dir"],
        **_evidence(**evidence_over),
    }


class FakeLauncher:
    """Stands in for ``subprocess.run``; ``behavior(job_dir, job)`` is the child."""

    def __init__(self, behavior: Callable[[Path, dict[str, Any]], Any]) -> None:
        self.behavior = behavior
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append((argv, kwargs))
        job_dir, job = _read_job(argv)
        out = self.behavior(job_dir, job)
        if isinstance(out, SimpleNamespace):
            return out
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _run_kwargs(tmp_path: Path, **over: Any) -> dict[str, Any]:
    for name in ("a", "b"):
        (tmp_path / name).mkdir(exist_ok=True)
    kw: dict[str, Any] = dict(
        base_model_path="/models/base",
        adapter_paths=[str(tmp_path / "a"), str(tmp_path / "b")],
        weights=[0.5, 0.5],
        combination_type="dare_ties",
        density=0.5,
        output_dir=tmp_path / "out" / "m1",
        capability_loss_threshold=0.05,
        capability_probe_path=None,
        abliteration_probe_path=None,
        timeout_s=30.0,
    )
    kw.update(over)
    return kw


def _assert_nothing_left(tmp_path: Path) -> None:
    assert not (tmp_path / "out" / "m1").exists()
    assert not (tmp_path / "out" / ".m1.partial").exists()


# --------------------------------------------------------------------------- #
# ChildMergeRunner
# --------------------------------------------------------------------------- #
def test_success_moves_staging_into_place_and_scrubs_the_job(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_STATE_KEY", "secret")
    monkeypatch.setenv("KAINE_ORGAN_API_KEY", "secret")
    seen: dict[str, Any] = {}

    def child(job_dir: Path, job: dict[str, Any]) -> None:
        seen["job_dir"] = job_dir
        seen["dir_mode"] = stat.S_IMODE(job_dir.stat().st_mode)
        seen["file_mode"] = stat.S_IMODE((job_dir / "job.json").stat().st_mode)
        seen["job"] = job
        assert not Path(job["staging_dir"]).exists()
        _stage_adapter(job)
        _write_result(job_dir, _ok_result(job))

    launcher = FakeLauncher(child)
    runner = ChildMergeRunner(python="/fake/python", run=launcher)
    outcome = runner.run(
        **_run_kwargs(
            tmp_path,
            capability_probe_path=str(tmp_path / "cap.jsonl"),
        )
    )

    out = tmp_path / "out" / "m1"
    assert outcome.merged_dir == out and outcome.rejection is None
    assert (out / "adapter_config.json").is_file()
    assert not (tmp_path / "out" / ".m1.partial").exists()

    argv, kwargs = launcher.calls[0]
    assert argv == [
        "/fake/python",
        "-m",
        "kaine.lifecycle.adapter_merge_worker",
        str(seen["job_dir"]),
    ]
    assert "shell" not in kwargs or kwargs["shell"] is False
    assert kwargs["timeout"] == 30.0
    assert kwargs["cwd"] == str(seen["job_dir"])
    env = kwargs["env"]
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
    assert "KAINE_STATE_KEY" not in env and "KAINE_ORGAN_API_KEY" not in env
    assert env["PYTHONPATH"] == str(REPO_ROOT)

    assert seen["dir_mode"] == 0o700 and seen["file_mode"] == 0o600
    job = seen["job"]
    assert job["base_model_path"] == "/models/base"
    assert job["adapter_paths"] == [str(tmp_path / "a"), str(tmp_path / "b")]
    assert job["weights"] == [0.5, 0.5]
    assert job["combination_type"] == "dare_ties"
    assert job["capability_probe_path"] == str(tmp_path / "cap.jsonl")
    assert job["abliteration_probe_path"] is None
    assert not seen["job_dir"].exists()  # the job directory is removed


def test_clean_rejection_is_returned_and_staging_removed(tmp_path):
    reason = {"adapter_merge": "ties_dare", "adapter_merge_rejected": "capability_loss=0.9"}

    def child(job_dir, job):
        _stage_adapter(job)  # a worker that forgot to clean up
        _write_result(
            job_dir,
            {"schema_version": 1, "ok": True, "rejection": reason},
        )

    outcome = ChildMergeRunner(run=FakeLauncher(child)).run(**_run_kwargs(tmp_path))
    assert outcome.merged_dir is None and outcome.rejection == reason
    _assert_nothing_left(tmp_path)


def _nonzero(job_dir, job):
    _stage_adapter(job)
    return SimpleNamespace(returncode=3, stdout="", stderr="boom: CUDA out of memory")


def _timeout(job_dir, job):
    _stage_adapter(job)
    raise subprocess.TimeoutExpired(cmd="x", timeout=30)


def _launch_error(job_dir, job):
    raise FileNotFoundError("no such interpreter")


def _no_result(job_dir, job):
    _stage_adapter(job)


def _garbage(job_dir, job):
    _stage_adapter(job)
    _write_result(job_dir, "{not json")


def _not_an_object(job_dir, job):
    _stage_adapter(job)
    _write_result(job_dir, "[1, 2]")


def _reported_failure(job_dir, job):
    _write_result(
        job_dir, {"schema_version": 1, "ok": False, "reason": "RuntimeError: nope"}
    )


def _wrong_schema(job_dir, job):
    _stage_adapter(job)
    _write_result(job_dir, {**_ok_result(job), "schema_version": 99})


def _success_without_output(job_dir, job):
    _write_result(job_dir, _ok_result(job))


def _success_with_empty_output(job_dir, job):
    Path(job["staging_dir"]).mkdir(parents=True)
    _write_result(job_dir, _ok_result(job))


def _success_without_adapter_config(job_dir, job):
    staging = Path(job["staging_dir"])
    staging.mkdir(parents=True)
    (staging / "junk.bin").write_text("x")
    _write_result(job_dir, _ok_result(job))


def _success_pointing_elsewhere(job_dir, job):
    _stage_adapter(job)
    _write_result(job_dir, {**_ok_result(job), "merged_dir": "/tmp/elsewhere"})


def _malformed_rejection(job_dir, job):
    _stage_adapter(job)
    _write_result(
        job_dir, {"schema_version": 1, "ok": True, "rejection": {"nope": 1}}
    )


def _no_evidence(job_dir, job):
    _stage_adapter(job)
    result = _ok_result(job)
    for key in _evidence():
        del result[key]
    _write_result(job_dir, result)


def _with_evidence(**over):
    def child(job_dir, job):
        _stage_adapter(job)
        _write_result(job_dir, _ok_result(job, **over))

    return child


@pytest.mark.parametrize(
    ("behavior", "match"),
    [
        (_nonzero, "(?s)exited 3.*CUDA out of memory"),
        (_timeout, "timed out after 30s"),
        (_launch_error, "could not be launched"),
        (_no_result, "wrote no result.json"),
        (_garbage, "unreadable"),
        (_not_an_object, "not an object"),
        (_reported_failure, "reported failure: RuntimeError: nope"),
        (_wrong_schema, "schema_version mismatch"),
        (_success_without_output, "missing or empty"),
        (_success_with_empty_output, "missing or empty"),
        (_success_without_adapter_config, "no adapter_config.json"),
        (_success_pointing_elsewhere, "not the staging directory"),
        (_malformed_rejection, "malformed rejection"),
        (_no_evidence, "abliteration_passed=None"),
        (_with_evidence(abliteration_passed=False), "abliteration_passed=False"),
        (_with_evidence(abliteration_passed="yes"), "abliteration_passed='yes'"),
        (_with_evidence(abliteration_probes_scored=0), "probes_scored=0"),
        (_with_evidence(abliteration_probes_scored=True), "probes_scored=True"),
        (_with_evidence(abliteration_probes_scored=2.0), "probes_scored=2.0"),
        (_with_evidence(abliteration_probes_scored=None), "probes_scored=None"),
        (_with_evidence(capability_score_parents=None), "invalid capability scores"),
        (_with_evidence(capability_score_parents=[0.5]), "invalid capability scores"),
        (_with_evidence(capability_score_parents=[0.5, 1.5]), "invalid capability scores"),
        (_with_evidence(capability_score_merged=None), "invalid capability scores"),
        (_with_evidence(capability_score_merged=float("nan")), "invalid capability scores"),
        (_with_evidence(capability_loss=None), "non-finite capability_loss"),
        (_with_evidence(capability_loss=float("inf")), "non-finite capability_loss"),
        (_with_evidence(capability_loss=True), "non-finite capability_loss"),
        (_with_evidence(capability_score_merged=0.64, capability_loss=0.06), "exceeds threshold"),
        # A child that under-reports its loss is refused: the parent recomputes it.
        (_with_evidence(capability_score_merged=0.4, capability_loss=0.0), "does not match its scores"),
    ],
)
def test_every_failure_raises_and_leaves_nothing_behind(tmp_path, behavior, match):
    runner = ChildMergeRunner(run=FakeLauncher(behavior))
    with pytest.raises(MergeWorkerError, match=match):
        runner.run(**_run_kwargs(tmp_path))
    _assert_nothing_left(tmp_path)


def test_valid_evidence_is_recorded_in_the_merge_meta(tmp_path, monkeypatch):
    merger = _merger(
        tmp_path,
        _with_evidence(
            capability_score_merged=0.68, capability_loss=0.02, abliteration_probes_scored=7
        ),
        monkeypatch,
    )
    paths, meta = merger.merge(*_parents(tmp_path))
    assert len(paths) == 1
    assert meta["abliteration_passed"] is True
    assert meta["abliteration_probes_scored"] == 7
    assert meta["capability_loss"] == pytest.approx(0.02)
    assert meta["capability_score_parents"] == [0.8, 0.6]
    assert meta["capability_score_merged"] == 0.68


def test_an_accepted_result_without_evidence_is_a_failed_merge(tmp_path, monkeypatch):
    a, b = _parents(tmp_path)
    paths, meta = _merger(tmp_path, _no_evidence, monkeypatch).merge(a, b)
    assert paths == a + b
    assert "abliteration_passed" in meta["adapter_merge_failed"]
    merged = tmp_path / "merged"
    assert not merged.exists() or list(merged.iterdir()) == []


def test_stderr_tail_has_paths_scrubbed(tmp_path):
    def child(job_dir, job):
        return SimpleNamespace(
            returncode=1, stdout="", stderr="cannot open /home/erik/secret/model.bin"
        )

    with pytest.raises(MergeWorkerError) as exc:
        ChildMergeRunner(run=FakeLauncher(child)).run(**_run_kwargs(tmp_path))
    assert "/home/erik" not in str(exc.value) and "<PATH>" in str(exc.value)


def test_stale_staging_siblings_older_than_the_timeout_are_swept(tmp_path):
    import time

    out = tmp_path / "out"
    out.mkdir()
    old = out / ".old-1.partial"
    young = out / ".young-1.partial"
    keep = out / "finished-merge"
    other = out / ".hidden"
    for d in (old, young, keep, other):
        d.mkdir()
    long_ago = time.time() - 100
    for d in (old, keep, other):
        os.utime(d, (long_ago, long_ago))

    ChildMergeRunner(run=FakeLauncher(_ok_child)).run(
        **_run_kwargs(tmp_path, timeout_s=30.0)
    )
    assert not old.exists()
    assert young.exists() and keep.exists() and other.exists()


def test_failure_scrubs_the_job_directory(tmp_path):
    jobs: list[Path] = []

    def child(job_dir, job):
        jobs.append(job_dir)
        return SimpleNamespace(returncode=1, stdout="", stderr="x")

    with pytest.raises(MergeWorkerError):
        ChildMergeRunner(run=FakeLauncher(child)).run(**_run_kwargs(tmp_path))
    assert jobs and not jobs[0].exists()


def test_existing_output_dir_is_refused_untouched(tmp_path):
    out = tmp_path / "out" / "m1"
    out.mkdir(parents=True)
    (out / "keep.txt").write_text("keep")
    launcher = FakeLauncher(lambda d, j: None)
    with pytest.raises(MergeWorkerError, match="already exists"):
        ChildMergeRunner(run=launcher).run(**_run_kwargs(tmp_path))
    assert launcher.calls == []
    assert (out / "keep.txt").read_text() == "keep"


def test_stale_staging_from_an_earlier_crash_is_cleared(tmp_path):
    stale = tmp_path / "out" / ".m1.partial"
    stale.mkdir(parents=True)
    (stale / "old.bin").write_text("old")

    def child(job_dir, job):
        _stage_adapter(job)  # would fail if the stale dir were still there
        _write_result(job_dir, _ok_result(job))

    outcome = ChildMergeRunner(run=FakeLauncher(child)).run(**_run_kwargs(tmp_path))
    assert not (outcome.merged_dir / "old.bin").exists()


# --------------------------------------------------------------------------- #
# TiesDareAdapterMerger over a child runner
# --------------------------------------------------------------------------- #
def _merger(tmp_path: Path, behavior, monkeypatch, **cfg: Any) -> TiesDareAdapterMerger:
    monkeypatch.setattr(am, "check_peft_available", lambda: None)
    config = TiesDareMergeConfig(
        output_dir=tmp_path / "merged",
        base_model_path="/models/base",
        **cfg,
    )
    return TiesDareAdapterMerger(
        config, runner=ChildMergeRunner(run=FakeLauncher(behavior))
    )


def _parents(tmp_path: Path) -> tuple[list[str], list[str]]:
    a, b = tmp_path / "pa", tmp_path / "pb"
    a.mkdir()
    b.mkdir()
    return [str(a)], [str(b)]


def _ok_child(job_dir, job):
    _stage_adapter(job)
    _write_result(job_dir, _ok_result(job))


def test_merger_accepts_a_child_merge(tmp_path, monkeypatch):
    merger = _merger(tmp_path, _ok_child, monkeypatch)
    paths, meta = merger.merge(*_parents(tmp_path))
    assert len(paths) == 1 and Path(paths[0]).is_dir()
    assert Path(paths[0]).parent == tmp_path / "merged"
    assert meta["adapter_merge"] == "ties_dare"
    assert meta["weights"] == [0.5, 0.5]
    assert "adapter_merge_failed" not in meta and "adapter_merge_rejected" not in meta


def test_merger_reports_a_child_rejection_as_a_veto(tmp_path, monkeypatch):
    def child(job_dir, job):
        _write_result(
            job_dir,
            {
                "schema_version": 1,
                "ok": True,
                "rejection": {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_rejected": "abliteration veto: deflected probe 'x'",
                },
            },
        )

    a, b = _parents(tmp_path)
    paths, meta = _merger(tmp_path, child, monkeypatch).merge(a, b)
    assert paths == a + b  # parents left uncombined
    assert "abliteration veto" in meta["adapter_merge_rejected"]
    assert not (tmp_path / "merged").exists() or not any((tmp_path / "merged").iterdir())


@pytest.mark.parametrize(
    "behavior",
    [_nonzero, _timeout, _no_result, _garbage, _reported_failure, _success_without_output],
)
def test_merger_treats_a_bad_child_as_a_failed_merge(tmp_path, monkeypatch, behavior):
    a, b = _parents(tmp_path)
    paths, meta = _merger(tmp_path, behavior, monkeypatch).merge(a, b)
    assert paths == a + b
    assert "MergeWorkerError" in meta["adapter_merge_failed"]
    assert "adapter_merge_rejected" not in meta
    merged = tmp_path / "merged"
    assert not merged.exists() or list(merged.iterdir()) == []


def test_job_carries_the_check_settings(tmp_path, monkeypatch):
    seen: dict[str, Any] = {}

    def child(job_dir, job):
        seen.update(job)
        _stage_adapter(job)
        _write_result(job_dir, _ok_result(job))

    merger = _merger(
        tmp_path,
        child,
        monkeypatch,
        capability_loss_threshold=0.1,
        capability_probe_path=str(tmp_path / "cap.jsonl"),
        abliteration_probe_path=str(tmp_path / "abl.jsonl"),
        combination_type="ties",
        merge_timeout_s=77,
    )
    merger.merge(*_parents(tmp_path))
    assert seen["capability_loss_threshold"] == 0.1
    assert seen["capability_probe_path"] == str(tmp_path / "cap.jsonl")
    assert seen["abliteration_probe_path"] == str(tmp_path / "abl.jsonl")
    assert seen["combination_type"] == "ties"
    assert merger._runner._run.calls[0][1]["timeout"] == 77


def test_in_process_seams_need_a_backend_and_exclude_a_runner(tmp_path):
    cfg = TiesDareMergeConfig(output_dir=tmp_path)
    with pytest.raises(ValueError, match="need an in-process backend"):
        TiesDareAdapterMerger(cfg, model_loader=lambda p: (None, None))
    with pytest.raises(ValueError, match="not both"):
        TiesDareAdapterMerger(cfg, backend=object(), runner=ChildMergeRunner())


def test_invalid_merge_timeout_is_refused(tmp_path):
    for bad in (0, -1, float("nan"), True, "5"):
        with pytest.raises(ValueError, match="merge_timeout_s"):
            TiesDareMergeConfig(output_dir=tmp_path, merge_timeout_s=bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# the parent stays clean
# --------------------------------------------------------------------------- #
def test_parent_imports_neither_transformers_nor_peft_for_a_merge(tmp_path):
    """Run in a fresh interpreter so earlier tests cannot mask an import."""
    code = textwrap.dedent(
        """
        import sys, json
        from pathlib import Path
        from types import SimpleNamespace
        from kaine.lifecycle.adapter_merge import (
            ChildMergeRunner, TiesDareAdapterMerger, TiesDareMergeConfig,
        )

        root = Path(sys.argv[1])

        def fake_run(argv, **kw):
            job_dir = Path(argv[-1])
            job = json.loads((job_dir / "job.json").read_text())
            staging = Path(job["staging_dir"])
            staging.mkdir(parents=True)
            (staging / "adapter_config.json").write_text("{}")
            (job_dir / "result.json").write_text(json.dumps({
                "schema_version": 1, "ok": True, "rejection": None,
                "merged_dir": job["staging_dir"],
                "abliteration_passed": True, "abliteration_probes_scored": 2,
                "capability_score_parents": [0.5, 0.5],
                "capability_score_merged": 0.5, "capability_loss": 0.0,
            }))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        for n in ("pa", "pb"):
            (root / n).mkdir()
        merger = TiesDareAdapterMerger(
            TiesDareMergeConfig(output_dir=root / "m", base_model_path="/b"),
            runner=ChildMergeRunner(run=fake_run),
        )
        paths, meta = merger.merge([str(root / "pa")], [str(root / "pb")])
        assert len(paths) == 1, meta
        bad = [m for m in ("transformers", "peft") if m in sys.modules]
        assert not bad, bad
        print("CLEAN")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT), "CUDA_VISIBLE_DEVICES": ""},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "CLEAN" in proc.stdout


def test_default_dtype_stays_float32_around_a_merge(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    assert torch.get_default_dtype() == torch.float32
    merger = _merger(tmp_path, _ok_child, monkeypatch)
    merger.merge(*_parents(tmp_path))
    assert torch.get_default_dtype() == torch.float32


def test_default_launcher_kills_the_whole_process_group_on_timeout(tmp_path):
    import time

    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(60)\n"
    )
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        am._run_in_own_session(
            [sys.executable, "-c", code],
            timeout=2,
            cwd=str(tmp_path),
            env=dict(os.environ),
            text=True,
            capture_output=True,
            check=False,
        )
    assert time.monotonic() - start < 30  # the pipes did not hang
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_default_launcher_returns_a_completed_process(tmp_path):
    proc = am._run_in_own_session(
        [sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"],
        timeout=30,
        cwd=str(tmp_path),
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 3 and proc.stdout.strip() == "out" and proc.stderr == "err"


def test_check_peft_available_does_not_import_peft(monkeypatch):
    """The availability probe is a spec lookup; importing peft would import
    transformers into the caller."""
    import importlib

    def boom(name, *a, **kw):  # pragma: no cover - failure path
        raise AssertionError(f"imported {name}")

    monkeypatch.setattr(am, "__import__", boom, raising=False)
    monkeypatch.setattr(importlib, "import_module", boom)
    am.check_peft_available()  # must not raise


# --------------------------------------------------------------------------- #
# the worker module
# --------------------------------------------------------------------------- #
def _job(tmp_path: Path, **over: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "schema_version": am.MERGE_SCHEMA_VERSION,
        "base_model_path": "/models/base",
        "adapter_paths": ["/a", "/b"],
        "weights": [0.5, 0.5],
        "combination_type": "dare_ties",
        "density": 0.5,
        "staging_dir": str(tmp_path / "stage"),
        "capability_loss_threshold": 0.05,
        "capability_probe_path": None,
        "abliteration_probe_path": None,
    }
    job.update(over)
    return job


class _Backend:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def merge(self, **kw: Any) -> Path:
        self.kwargs = kw
        out: Path = kw["output_dir"]
        out.mkdir(parents=True)
        (out / "adapter_config.json").write_text("{}")
        return out


class _Eval:
    def __init__(self, score: float) -> None:
        self.score = score

    async def eval(self, model: Any, tokenizer: Any) -> float:
        return self.score


class _Scorer:
    def __init__(self, passed: bool = True) -> None:
        self.passed = passed

    async def score(self, model: Any, tokenizer: Any) -> Any:
        return SimpleNamespace(
            passed=self.passed, failed_probe="p", matched_pattern="I cannot", probes_scored=1
        )


def _worker():
    from kaine.lifecycle import adapter_merge_worker

    return adapter_merge_worker


def test_worker_run_job_keeps_a_passing_merge(tmp_path):
    w = _worker()
    backend = _Backend()
    result = w.run_job(
        _job(tmp_path),
        backend=backend,
        capability_eval=_Eval(0.8),
        abliteration_scorer=_Scorer(True),
        model_loader=lambda p: (object(), object()),
    )
    assert result["ok"] is True and result["rejection"] is None
    assert result["merged_dir"] == str(tmp_path / "stage")
    assert result["abliteration_passed"] is True
    assert result["abliteration_probes_scored"] == 1
    assert result["capability_score_parents"] == [0.8, 0.8]
    assert result["capability_score_merged"] == 0.8
    assert result["capability_loss"] == 0.0
    assert (tmp_path / "stage" / "adapter_config.json").is_file()
    assert backend.kwargs["output_dir"] == tmp_path / "stage"
    assert backend.kwargs["weights"] == [0.5, 0.5]


def test_worker_run_job_rejection_removes_staging(tmp_path):
    w = _worker()
    result = w.run_job(
        _job(tmp_path),
        backend=_Backend(),
        capability_eval=_Eval(0.8),
        abliteration_scorer=_Scorer(False),
        model_loader=lambda p: (object(), object()),
    )
    assert "abliteration veto" in result["rejection"]["adapter_merge_rejected"]
    assert not (tmp_path / "stage").exists()


def test_worker_run_job_exception_removes_staging(tmp_path):
    w = _worker()

    class _Boom(_Backend):
        def merge(self, **kw):
            super().merge(**kw)
            raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        w.run_job(
            _job(tmp_path),
            backend=_Boom(),
            capability_eval=_Eval(0.8),
            abliteration_scorer=_Scorer(True),
            model_loader=lambda p: (object(), object()),
        )
    assert not (tmp_path / "stage").exists()


def test_worker_refuses_an_existing_staging_dir(tmp_path):
    w = _worker()
    (tmp_path / "stage").mkdir()
    (tmp_path / "stage" / "other.txt").write_text("mine")
    with pytest.raises(w.MergeJobError, match="already exists"):
        w.run_job(_job(tmp_path), backend=_Backend())
    assert (tmp_path / "stage" / "other.txt").exists()


def test_worker_main_writes_private_result_atomically(tmp_path, monkeypatch):
    w = _worker()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(_job(tmp_path)))
    monkeypatch.setattr(
        w,
        "run_job",
        lambda job: {"schema_version": 1, "ok": True, "rejection": None, "merged_dir": "x"},
    )
    assert w.main([str(job_dir)]) == 0
    result_path = job_dir / "result.json"
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert json.loads(result_path.read_text())["ok"] is True
    assert not (job_dir / "result.json.tmp").exists()


def test_worker_main_reports_failure_and_exits_nonzero(tmp_path, monkeypatch):
    w = _worker()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(_job(tmp_path)))

    def boom(job):
        raise RuntimeError("load failed")

    monkeypatch.setattr(w, "run_job", boom)
    assert w.main([str(job_dir)]) == 1
    result = json.loads((job_dir / "result.json").read_text())
    assert result["ok"] is False and "load failed" in result["reason"]


@pytest.mark.parametrize(
    "over",
    [
        {"schema_version": 99},
        {"base_model_path": ""},
        {"adapter_paths": ["/only-one"], "weights": [1.0]},
        {"weights": [1.0]},
        {"combination_type": "average"},
        {"density": True},
        {"staging_dir": 3},
        {"capability_probe_path": 5},
    ],
)
def test_worker_rejects_a_malformed_job(tmp_path, over):
    w = _worker()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(_job(tmp_path, **over)))
    with pytest.raises(w.MergeJobError):
        w.read_job(job_dir)
    assert w.main([str(job_dir)]) == 1  # reported, not crashed
    assert json.loads((job_dir / "result.json").read_text())["ok"] is False


def test_worker_builds_its_checks_from_the_job_probe_paths(tmp_path, monkeypatch):
    """Without injected seams the worker builds the real probe-set evaluators,
    and the capability evaluator refuses an empty probe set."""
    w = _worker()
    cap = tmp_path / "cap.jsonl"
    abl = tmp_path / "abl.jsonl"
    cap.write_text("")  # empty: must fail closed
    abl.write_text(json.dumps({"prompt": "p", "deflection_patterns": ["I cannot"]}) + "\n")

    result = w.run_job(
        _job(
            tmp_path,
            capability_probe_path=str(cap),
            abliteration_probe_path=str(abl),
        ),
        backend=_Backend(),
        model_loader=lambda p: (object(), object()),
    )
    assert "adapter_merge_rejected" in result["rejection"]
    assert "capability probe set is empty" in result["rejection"]["adapter_merge_rejected"]
    assert not (tmp_path / "stage").exists()


# --------------------------------------------------------------------------- #
# real merge through a real child process
# --------------------------------------------------------------------------- #
def _have(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


@pytest.mark.skipif(
    not (_have("peft") and _have("torch") and _have("transformers") and _have("tokenizers")),
    reason="needs peft, torch, transformers and tokenizers",
)
def test_real_merge_of_two_tiny_adapters_in_a_child_process(tmp_path):
    import torch
    from peft import LoraConfig, get_peft_model
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

    words = ["[UNK]", "[EOS]"] + [f"w{i}" for i in range(62)]
    tok = Tokenizer(models.WordLevel({w: i for i, w in enumerate(words)}, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    fast = PreTrainedTokenizerFast(
        tokenizer_object=tok, unk_token="[UNK]", eos_token="[EOS]", pad_token="[EOS]"
    )
    cfg = LlamaConfig(
        vocab_size=len(words),
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=2,
        num_key_value_heads=2,
        max_position_embeddings=64,
        eos_token_id=1,
        pad_token_id=1,
    )
    torch.manual_seed(0)
    base_dir = tmp_path / "base"
    LlamaForCausalLM(cfg).save_pretrained(base_dir)
    fast.save_pretrained(base_dir)

    adapters = []
    for seed in (1, 2):
        torch.manual_seed(seed)
        model = LlamaForCausalLM.from_pretrained(base_dir)
        peft_model = get_peft_model(
            model,
            LoraConfig(
                r=2,
                lora_alpha=4,
                target_modules=["q_proj", "v_proj"],
                init_lora_weights=False,
            ),
        )
        path = tmp_path / f"adapter_{seed}"
        peft_model.save_pretrained(str(path))
        adapters.append(str(path))

    cap = tmp_path / "cap.jsonl"
    cap.write_text(json.dumps({"prompt": "w1 w2", "expected": "w3"}) + "\n")
    abl = tmp_path / "abl.jsonl"
    abl.write_text(
        json.dumps({"prompt": "w4 w5", "deflection_patterns": ["I cannot"]}) + "\n"
    )

    merger = TiesDareAdapterMerger(
        TiesDareMergeConfig(
            output_dir=tmp_path / "merged",
            base_model_path=str(base_dir),
            capability_probe_path=str(cap),
            abliteration_probe_path=str(abl),
            capability_loss_threshold=0.99,
            merge_timeout_s=600,
        )
    )
    paths, meta = merger.merge([adapters[0]], [adapters[1]])

    assert "adapter_merge_failed" not in meta, meta
    assert "adapter_merge_rejected" not in meta, meta
    (merged,) = [Path(p) for p in paths]
    assert merged.parent == tmp_path / "merged" and merged.is_dir()
    assert (merged / "adapter_config.json").is_file()
    assert (merged / "adapter_model.safetensors").is_file()
    assert not (merged / "merged").exists()
    assert not list((tmp_path / "merged").glob(".*.partial"))
    assert meta["abliteration_passed"] is True
    assert meta["abliteration_probes_scored"] >= 1
    assert meta["capability_loss"] <= 0.99
    assert len(meta["capability_score_parents"]) == 2
    assert torch.get_default_dtype() == torch.float32
