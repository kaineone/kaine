# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the in-process voice-alignment trainer path."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from kaine.modules.hypnos.subprocess_trainer import (
    SubprocessTrainerError,
    SubprocessVoiceTrainer,
)
from kaine.modules.hypnos.voice_alignment import DPOPair, VoiceAlignmentConfig


def _voice_config(tmp_path: Path, **overrides) -> VoiceAlignmentConfig:
    (tmp_path / "cap.jsonl").write_text(
        '{"prompt": "p", "expected": "e"}\n', encoding="utf-8"
    )
    (tmp_path / "abl.jsonl").write_text(
        '{"prompt": "p", "pattern": "ok"}\n', encoding="utf-8"
    )
    base = dict(
        intent_log_path=str(tmp_path / "intent.jsonl"),
        adapter_output_dir=str(tmp_path / "adapters"),
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="in_process",
        trainer_workdir=str(tmp_path / "work"),
        capability_probe_path=str(tmp_path / "cap.jsonl"),
        abliteration_probe_path=str(tmp_path / "abl.jsonl"),
        adapter_retention=0,
    )
    base.update(overrides)
    return VoiceAlignmentConfig(**base)


def _dpo_pair() -> DPOPair:
    return DPOPair(prompt="hi", chosen="hello", rejected="go away", system="s")


def _write_stub_script(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture
def trainer_factory(tmp_path: Path):
    def _make(entry_script: Path, **kwargs):
        defaults = {
            "trainer_python": None,
            "trainer_workdir": tmp_path / "work",
            "run_in_process": True,
            "entry_script": entry_script,
            "timeout_s": 10,
        }
        defaults.update(kwargs)
        return SubprocessVoiceTrainer(**defaults)

    return _make


@pytest.mark.asyncio
async def test_in_process_runs_stub_script_and_accepts(tmp_path: Path, trainer_factory):
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        """
        import json
        from pathlib import Path

        def main(argv):
            job_dir = Path(argv[1])
            job = json.loads((job_dir / "job.json").read_text())
            out_dir = Path(job["adapter_output_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = "20261005T120000"
            adapter_dir = out_dir / ts
            adapter_dir.mkdir(parents=True, exist_ok=True)
            (adapter_dir / "adapter_config.json").write_text("{}")
            (adapter_dir / "adapter.bin").write_text("weights")
            result = {
                "ok": True,
                "accepted": True,
                "schema_version": 2,
                "abliteration_passed": True,
                "abliteration_probes_scored": 1,
                "capability_loss": 0.0,
                "adapter_dir": str(adapter_dir),
                "reason": "accepted",
                "samples_used": 1,
                "dpo_loss": 0.1,
            }
            (job_dir / "result.json").write_text(json.dumps(result))
            return 0
        """,
    )

    trainer = trainer_factory(entry)
    config = _voice_config(tmp_path)
    result = await trainer.train([_dpo_pair()], config)

    assert result.accepted
    assert result.adapter_path == adapters / "20261005T120000"
    assert result.metadata["backend"] == "in_process"


@pytest.mark.asyncio
async def test_in_process_main_raises_subprocess_error(tmp_path: Path, trainer_factory):
    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        """
        def main(argv):
            raise RuntimeError("training blew up")
        """,
    )

    trainer = trainer_factory(entry)
    config = _voice_config(tmp_path)
    with pytest.raises(SubprocessTrainerError, match="RuntimeError"):
        await trainer.train([_dpo_pair()], config)


@pytest.mark.asyncio
async def test_in_process_non_zero_return_code_raises(tmp_path: Path, trainer_factory):
    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        """
        def main(argv):
            return 3
        """,
    )

    trainer = trainer_factory(entry)
    config = _voice_config(tmp_path)
    with pytest.raises(SubprocessTrainerError, match="exited 3"):
        await trainer.train([_dpo_pair()], config)


@pytest.mark.asyncio
async def test_in_process_adapter_outside_output_dir_refused(
    tmp_path: Path, trainer_factory
):
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    evil = tmp_path / "evil"
    evil.mkdir()
    evil_adapter = evil / "adapter"
    evil_adapter.mkdir()
    (evil_adapter / "adapter_config.json").write_text("{}")
    (evil_adapter / "adapter.bin").write_text("weights")

    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        f"""
        import json
        from pathlib import Path

        def main(argv):
            job_dir = Path(argv[1])
            result = {{
                "ok": True,
                "accepted": True,
                "schema_version": 2,
                "abliteration_passed": True,
                "abliteration_probes_scored": 1,
                "capability_loss": 0.0,
                "adapter_dir": {str(evil_adapter)!r},
                "reason": "accepted",
                "samples_used": 1,
                "dpo_loss": 0.1,
            }}
            (job_dir / "result.json").write_text(json.dumps(result))
            return 0
        """,
    )

    trainer = trainer_factory(entry)
    config = _voice_config(tmp_path)
    with pytest.raises(SubprocessTrainerError, match="is not strictly inside"):
        await trainer.train([_dpo_pair()], config)


@pytest.mark.asyncio
async def test_in_process_retention_prunes_old_adapter(tmp_path: Path, trainer_factory):
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    old_dir = adapters / "20261004T120000"
    old_dir.mkdir()
    (old_dir / "adapter_config.json").write_text("{}")
    (old_dir / "adapter.bin").write_text("old")
    current = adapters / "current"
    os.symlink(str(old_dir.relative_to(adapters)), current)

    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        """
        import json
        import os
        from pathlib import Path

        def main(argv):
            job_dir = Path(argv[1])
            job = json.loads((job_dir / "job.json").read_text())
            out_dir = Path(job["adapter_output_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = "20261005T120000"
            tmp = out_dir / f"{ts}.tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "adapter_config.json").write_text("{}")
            (tmp / "adapter.bin").write_text("new")
            final = out_dir / ts
            os.replace(tmp, final)

            link = out_dir / "current"
            swap = out_dir / "current.swap"
            if swap.exists() or swap.is_symlink():
                swap.unlink()
            os.symlink(final.name, swap)
            os.replace(swap, link)

            result = {
                "ok": True,
                "accepted": True,
                "schema_version": 2,
                "abliteration_passed": True,
                "abliteration_probes_scored": 1,
                "capability_loss": 0.0,
                "adapter_dir": str(final),
                "reason": "accepted",
                "samples_used": 1,
                "dpo_loss": 0.1,
            }
            (job_dir / "result.json").write_text(json.dumps(result))
            return 0
        """,
    )

    trainer = trainer_factory(entry)
    config = _voice_config(tmp_path, adapter_retention=1)
    result = await trainer.train([_dpo_pair()], config)

    assert result.accepted
    assert result.adapter_path == adapters / "20261005T120000"
    assert not old_dir.exists()
    assert result.metadata.get("evicted_adapters")
    assert str(old_dir) in result.metadata["evicted_adapters"]


@pytest.mark.asyncio
async def test_in_process_scrubs_job_inputs_after_run(tmp_path: Path, trainer_factory):
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    old_dir = adapters / "20261004T120000"
    old_dir.mkdir()
    (old_dir / "adapter_config.json").write_text("{}")
    (old_dir / "adapter.bin").write_text("old")
    current = adapters / "current"
    os.symlink(str(old_dir.relative_to(adapters)), current)

    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        """
        import json
        from pathlib import Path

        def main(argv):
            job_dir = Path(argv[1])
            job = json.loads((job_dir / "job.json").read_text())
            out_dir = Path(job["adapter_output_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = "20261005T120000"
            adapter_dir = out_dir / ts
            adapter_dir.mkdir(parents=True, exist_ok=True)
            (adapter_dir / "adapter_config.json").write_text("{}")
            (adapter_dir / "adapter.bin").write_text("weights")
            result = {
                "ok": True,
                "accepted": True,
                "adapter_dir": str(adapter_dir),
                "reason": "accepted",
                "capability_loss": 0.0,
                "abliteration_passed": True,
                "abliteration_probes_scored": 1,
                "schema_version": 2,
            }
            (job_dir / "result.json").write_text(json.dumps(result))
            return 0
        """,
    )

    trainer = trainer_factory(entry)
    config = _voice_config(tmp_path)
    await trainer.train([_dpo_pair()], config)

    job_dirs = [d for d in (tmp_path / "work").iterdir() if d.is_dir()]
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]
    assert not (job_dir / "pairs.jsonl").exists()
    assert not (job_dir / "previous_adapter").exists()


def _load_external_script():
    import importlib.util

    from kaine.modules.hypnos.subprocess_trainer import EXTERNAL_ENTRY_SCRIPT

    spec = importlib.util.spec_from_file_location(
        "hypnos_external_train_script", EXTERNAL_ENTRY_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promote_refuses_cancelled_job(tmp_path: Path):
    script = _load_external_script()
    adapter_root = tmp_path / "adapters"
    adapter_root.mkdir()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    tmp_dir = adapter_root / "20261005T120000.tmp"
    tmp_dir.mkdir()
    (tmp_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    final_dir = adapter_root / "20261005T120000"
    (job_dir / "CANCELLED").write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="job cancelled; not promoting"):
        script._promote(tmp_dir, final_dir, job_dir)

    assert not tmp_dir.exists()
    assert not final_dir.exists()
    assert not (adapter_root / "current").exists()


@pytest.mark.asyncio
async def test_in_process_timeout_writes_cancelled_marker(tmp_path: Path, trainer_factory):
    entry = tmp_path / "slow_stub.py"
    _write_stub_script(
        entry,
        """
        import time
        def main(argv):
            time.sleep(2)
            return 0
        """,
    )

    trainer = trainer_factory(entry, timeout_s=0.2)
    config = _voice_config(tmp_path)
    with pytest.raises(SubprocessTrainerError, match="timed out"):
        await trainer.train([_dpo_pair()], config)

    job_dirs = [d for d in (tmp_path / "work").iterdir() if d.is_dir()]
    assert any((d / "CANCELLED").exists() for d in job_dirs)


@pytest.mark.asyncio
async def test_constructor_sweeps_stale_inputs_and_train_sweeps_tmp_dirs(
    tmp_path: Path, trainer_factory
):
    work = tmp_path / "work"
    stale = work / "job-20261005T120000-001"
    stale.mkdir(parents=True)
    (stale / "pairs.jsonl").write_text('{"prompt": "p"}', encoding="utf-8")
    (stale / "previous_adapter").mkdir()
    (stale / "previous_adapter" / "adapter_config.json").write_text("{}", encoding="utf-8")

    adapters = tmp_path / "adapters"
    adapters.mkdir()
    promoted = adapters / "20261004T120000"
    promoted.mkdir()
    (promoted / "adapter_config.json").write_text("{}", encoding="utf-8")
    current = adapters / "current"
    os.symlink(str(promoted.relative_to(adapters)), current)
    tmp_stale = adapters / "2026.tmp"
    tmp_stale.mkdir()
    (tmp_stale / "adapter_config.json").write_text("{}", encoding="utf-8")

    entry = tmp_path / "stub_train.py"
    _write_stub_script(
        entry,
        """
        import json
        from pathlib import Path

        def main(argv):
            job_dir = Path(argv[1])
            job = json.loads((job_dir / "job.json").read_text())
            out_dir = Path(job["adapter_output_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = "20261005T120000"
            adapter_dir = out_dir / ts
            adapter_dir.mkdir(parents=True, exist_ok=True)
            (adapter_dir / "adapter_config.json").write_text("{}")
            (adapter_dir / "adapter.bin").write_text("weights")
            result = {
                "ok": True,
                "accepted": True,
                "adapter_dir": str(adapter_dir),
                "reason": "accepted",
                "capability_loss": 0.0,
                "abliteration_passed": True,
                "abliteration_probes_scored": 1,
                "schema_version": 2,
            }
            (job_dir / "result.json").write_text(json.dumps(result))
            return 0
        """,
    )

    trainer = trainer_factory(entry)
    assert not (stale / "pairs.jsonl").exists()
    assert not (stale / "previous_adapter").exists()
    assert promoted.exists()
    assert current.is_symlink()

    config = _voice_config(tmp_path)
    result = await trainer.train([_dpo_pair()], config)
    assert result.accepted
    assert not tmp_stale.exists()
    assert promoted.exists()
    assert (adapters / "current").is_symlink()
