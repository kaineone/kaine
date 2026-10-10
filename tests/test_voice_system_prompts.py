
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import asyncio
import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.boot.errors import VoiceAlignmentConfigError
from kaine.boot.factories.hypnos import voice_alignment_config_from_section
from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.hypnos import Hypnos, TrainingResult
from kaine.modules.hypnos.subprocess_trainer import SubprocessTrainerError, write_job_spec
from kaine.modules.hypnos.voice_alignment import DPOPair, VoiceAlignmentConfig
from kaine.modules.lingua import EXTERNAL_STREAM, FakeChatClient, IntentExpressionLog, Lingua
from kaine.persistence.system_prompts import (
    digest_of,
    read_system_prompt,
    store_bytes,
    store_dir_for,
    write_system_prompt,
)
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    is_encrypted,
    set_state_encryptor,
)


@pytest.fixture(autouse=True)
def _reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _enable(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))


async def _wait_for_entries(bus: AsyncBus, stream: str, *, timeout_s: float = 2.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        entries = await bus.client.xrange(stream)
        if entries:
            return entries
        await asyncio.sleep(0.02)
    return await bus.client.xrange(stream)


def _payloads(entries):
    out = []
    for _entry_id, fields in entries:
        raw = fields.get("payload")
        if isinstance(raw, str):
            out.append(json.loads(raw))
        elif raw:
            out.append(raw)
    return out


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _make_lingua(bus: AsyncBus, tmp_path: Path, responses=None) -> Lingua:
    return Lingua(
        bus,
        chat_client=FakeChatClient(responses=responses),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


async def _say(lingua, *, about, snapshot, about_kind):
    return await lingua._produce_inner(
        about=about,
        snapshot=snapshot,
        mode="external",
        stream=EXTERNAL_STREAM,
        about_kind=about_kind,
    )


def _event(source, type_, payload, salience=0.6):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


class _FakeMnemos:
    def __init__(self) -> None:
        self.consolidated = 0
        self.downscale_calls = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidated += 1
        return 5

    def downscale_activations(self, factor: float) -> int:
        self.downscale_calls.append(factor)
        return 0

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class _FakeThymos:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


class _FakeNous:
    @property
    def running(self) -> bool:
        return True

    async def step(self, n: int) -> list[str]:
        return []


class _FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


class _RejectingTrainer:
    async def train(self, pairs, config):
        return TrainingResult(
            accepted=False,
            adapter_path=None,
            capability_loss=0.0,
            reason="rejected",
            samples_used=len(pairs),
        )


class _RecordingTrainer:
    def __init__(self):
        self.calls = 0

    async def train(self, pairs, config):
        self.calls += 1
        return TrainingResult(
            accepted=True,
            adapter_path="/x",
            capability_loss=0.0,
            reason="ok",
            samples_used=len(pairs),
        )


def _make_hypnos(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_log_path: Path | None = None,
    trainer=None,
):
    if intent_log_path is None:
        intent_log_path = tmp_path / "intent.jsonl"
    config = VoiceAlignmentConfig(
        intent_log_path=intent_log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    return Hypnos(
        bus,
        mnemos=_FakeMnemos(),
        nous_process=_FakeNous(),
        thymos=_FakeThymos(),
        chronos_resetters=[_FakeResetter()],
        trainer=trainer or _RejectingTrainer(),
        voice_alignment_config=config,
    )


def test_store_round_trip_encrypted(monkeypatch, tmp_path):
    _enable(monkeypatch)
    store_dir = tmp_path / "system_prompts"
    text = "persona: you are a helpful being"
    digest = write_system_prompt(store_dir, text)

    files = list(store_dir.iterdir())
    assert len(files) == 1
    raw = files[0].read_bytes()
    decoded = base64.b64decode(raw, validate=True)
    assert is_encrypted(decoded)
    assert text.encode("utf-8") not in raw

    assert read_system_prompt(store_dir, digest) == text


def test_store_round_trip_plaintext(tmp_path):
    store_dir = tmp_path / "system_prompts"
    text = "persona: plain"
    digest = write_system_prompt(store_dir, text)
    assert read_system_prompt(store_dir, digest) == text


def test_read_system_prompt_verification(monkeypatch, tmp_path):
    store_dir = tmp_path / "system_prompts"
    text = "real persona"
    digest = write_system_prompt(store_dir, text)

    (store_dir / f"{digest}.txt").write_text("wrong text", encoding="utf-8")
    assert read_system_prompt(store_dir, digest) is None

    assert read_system_prompt(store_dir, "not-hex") is None
    assert read_system_prompt(store_dir, "a" * 64) is None
    assert read_system_prompt(store_dir, "Z" * 64) is None
    assert read_system_prompt(store_dir, digest + "0") is None

    _enable(monkeypatch)
    other = "other persona"
    other_digest = write_system_prompt(store_dir, other)
    monkeypatch.setenv(
        "KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii")
    )
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    assert read_system_prompt(store_dir, other_digest) is None


def test_write_system_prompt_once(monkeypatch, tmp_path):
    store_dir = tmp_path / "system_prompts"
    text = "prompt text"
    calls = []

    original_replace = os.replace

    def counting_replace(src, dst):
        calls.append(1)
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", counting_replace)

    d1 = write_system_prompt(store_dir, text)
    d2 = write_system_prompt(store_dir, text)
    assert d1 == d2
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_heard_sentinel_never_in_system_prompt_store(bus: AsyncBus, tmp_path: Path):
    sentinel = "PURPLE-HERON-4471 said this"
    lingua = _make_lingua(bus, tmp_path, responses=["A reply."])
    await lingua.initialize()
    try:
        heard = _snapshot(
            [
                (
                    "t1",
                    _event(
                        "audition",
                        "audition.transcription",
                        {"text": sentinel},
                        0.9,
                    ),
                )
            ]
        )
        await _say(lingua, about=sentinel, snapshot=heard, about_kind="heard")

        records = _records(tmp_path / "intent.jsonl")
        assert len(records) == 1
        system_digest = records[0]["system_digest"]

        store_dir = store_dir_for(tmp_path / "intent.jsonl")
        files = list(store_dir.iterdir())
        assert len(files) == 1
        assert files[0].name == f"{system_digest}.txt"

        for path in files:
            decrypted = get_state_encryptor().maybe_decrypt(path.read_bytes()).decode("utf-8")
            assert sentinel not in decrypted
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_attach_system_prompts_keeps_verified_drops_bad(bus: AsyncBus, tmp_path: Path):
    log_path = tmp_path / "intent.jsonl"
    store_dir = store_dir_for(log_path)
    good = "good system prompt"
    bad = "bad system prompt"
    good_digest = write_system_prompt(store_dir, good)
    bad_digest = digest_of(bad)
    (store_dir / f"{bad_digest}.txt").write_bytes(
        get_state_encryptor().encrypt((bad[:-1]).encode("utf-8"))
    )

    h = _make_hypnos(bus, tmp_path, intent_log_path=log_path)
    pairs = [
        DPOPair("p1", "c1", "r1", metadata={"system_digest": good_digest}),
        DPOPair("p2", "c2", "r2", metadata={"system_digest": "missing"}),
        DPOPair("p3", "c3", "r3", metadata={"system_digest": bad_digest}),
    ]

    kept, dropped = await h._attach_system_prompts(pairs)
    assert dropped == 2
    assert len(kept) == 1
    assert kept[0].system == good


@pytest.mark.asyncio
async def test_train_on_pairs_no_verified_pairs(bus: AsyncBus, tmp_path: Path):
    h = _make_hypnos(bus, tmp_path, trainer=_RecordingTrainer())
    pairs = [DPOPair("p", "c", "r", metadata={"system_digest": "missing"})]
    start_ms = time.monotonic() * 1000.0

    result, phase = await h._train_on_pairs(pairs, start_ms, lambda m: m)
    assert result.accepted is False
    assert "no pair has a verified system prompt" in result.reason
    assert h._trainer.calls == 0
    assert phase.metadata["pairs_without_system"] == 1


def test_job_spec_writes_system_and_precision_and_schema(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        train_precision="4bit",
    )
    pairs = [DPOPair("p", "c", "r", system="sys", metadata={"system_digest": "d"})]
    write_job_spec(
        job_dir,
        pairs,
        config,
        base_path="/base",
        adapter_output_dir=str(tmp_path / "out"),
    )

    rows = [json.loads(line) for line in (job_dir / "pairs.jsonl").read_text().splitlines()]
    assert rows == [{"prompt": "p", "chosen": "c", "rejected": "r", "system": "sys"}]

    job = json.loads((job_dir / "job.json").read_text())
    assert job["schema_version"] == 2
    assert job["train_precision"] == "4bit"
    assert job["previous_adapter_dir"] is None


def test_job_spec_copies_current_adapter(tmp_path):
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir(parents=True)
    current = adapter_dir / "2025-10-05T00-00-00"
    current.mkdir()
    (current / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter_dir / "current").symlink_to(current, target_is_directory=True)

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=adapter_dir,
    )
    write_job_spec(
        job_dir,
        [],
        config,
        base_path="/base",
        adapter_output_dir=str(tmp_path / "out"),
    )

    assert (job_dir / "previous_adapter" / "adapter_config.json").exists()
    job = json.loads((job_dir / "job.json").read_text())
    assert job["previous_adapter_dir"] == "previous_adapter"


def test_job_spec_refuses_broken_current_link(tmp_path):
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "current").symlink_to(
        adapter_dir / "nonexistent", target_is_directory=True
    )

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=adapter_dir,
    )
    with pytest.raises(SubprocessTrainerError):
        write_job_spec(
            job_dir,
            [],
            config,
            base_path="/base",
            adapter_output_dir=str(tmp_path / "out"),
        )


def test_voice_alignment_config_rejects_bad_precision():
    with pytest.raises(ValueError, match="train_precision"):
        VoiceAlignmentConfig(
            intent_log_path=Path("x"),
            adapter_output_dir=Path("y"),
            train_precision="8bit",
        )


def test_factory_rejects_and_accepts_train_precision():
    with pytest.raises(VoiceAlignmentConfigError, match="train_precision"):
        voice_alignment_config_from_section({"train_precision": "8bit"})

    with pytest.raises(VoiceAlignmentConfigError, match="train_precision"):
        voice_alignment_config_from_section({"train_precision": 7})

    cfg = voice_alignment_config_from_section({"train_precision": "4bit"})
    assert cfg.train_precision == "4bit"

    cfg = voice_alignment_config_from_section({"enabled": False})
    assert cfg.train_precision == "bf16"


def test_store_bytes_sums_files(tmp_path):
    store_dir = tmp_path / "system_prompts"
    write_system_prompt(store_dir, "one")
    write_system_prompt(store_dir, "two")
    assert store_bytes(store_dir) > 0


@pytest.mark.asyncio
async def test_subprocess_job_inputs_are_private_and_scrubbed(tmp_path, monkeypatch):
    """pairs.jsonl (prompts, utterances, decrypted persona) and the copied
    adapter are owner-only while the trainer runs and gone once it returns."""
    import stat

    from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer

    adapters = tmp_path / "adapters"
    prev = adapters / "20260101T000000"
    prev.mkdir(parents=True)
    (prev / "adapter_config.json").write_text("{}")
    os.symlink(prev.name, adapters / "current")
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=adapters,
        base_model_path=str(tmp_path / "base"),
    )
    seen: dict = {}

    async def fake_run(self, job_dir, *, samples_used, adapter_root=None, capability_loss_threshold=0.05):
        seen["dir_mode"] = stat.S_IMODE(job_dir.stat().st_mode)
        seen["pairs_mode"] = stat.S_IMODE((job_dir / "pairs.jsonl").stat().st_mode)
        seen["job_mode"] = stat.S_IMODE((job_dir / "job.json").stat().st_mode)
        seen["had_adapter"] = (job_dir / "previous_adapter" / "adapter_config.json").exists()
        seen["job_dir"] = job_dir
        return {"ok": True, "accepted": False, "reason": "test", "schema_version": 2}

    monkeypatch.setattr(SubprocessVoiceTrainer, "_run_subprocess", fake_run)
    trainer = SubprocessVoiceTrainer(
        trainer_python="/nonexistent/python", trainer_workdir=tmp_path / "work"
    )
    pair = DPOPair(prompt="p", chosen="c", rejected="r", system="persona")
    await trainer.train([pair], config)

    assert seen["dir_mode"] == 0o700
    assert seen["pairs_mode"] == 0o600
    assert seen["job_mode"] == 0o600
    assert seen["had_adapter"] is True
    assert not (seen["job_dir"] / "pairs.jsonl").exists()
    assert not (seen["job_dir"] / "previous_adapter").exists()


def test_trainer_env_withholds_secrets_and_forces_offline():
    from kaine.modules.hypnos.subprocess_trainer import trainer_env

    env = trainer_env(
        {
            "PATH": "/usr/bin",
            "KAINE_STATE_KEY": "secret",
            "KAINE_ORGAN_API_KEY": "secret",
            "KAINE_NEXUS_TOKEN": "secret",
            "CUDA_VISIBLE_DEVICES": "0",
        }
    )
    assert env["PATH"] == "/usr/bin"
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert not any(k.startswith("KAINE_") for k in env)
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"


@pytest.mark.asyncio
async def test_reported_adapter_outside_the_output_dir_is_refused(tmp_path, monkeypatch):
    import subprocess as sp

    from kaine.modules.hypnos.subprocess_trainer import (
        SubprocessTrainerError,
        SubprocessVoiceTrainer,
    )

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "adapter_config.json").write_text("{}")
    seen_env = {}

    def fake_run(argv, cwd, env, **kwargs):
        seen_env.update(env)
        (Path(cwd) / "result.json").write_text(
            json.dumps({
                "ok": True,
                "accepted": True,
                "schema_version": 2,
                "abliteration_passed": True,
                "abliteration_probes_scored": 1,
                "capability_loss": 0.0,
                "adapter_dir": str(outside),
                "reason": "accepted",
                "samples_used": 1,
                "dpo_loss": 0.1,
            })
        )
        return sp.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("kaine.modules.hypnos.subprocess_trainer.subprocess.run", fake_run)
    monkeypatch.setenv("KAINE_STATE_KEY", "secret")
    script = tmp_path / "entry.py"
    script.write_text("")
    trainer = SubprocessVoiceTrainer(
        trainer_python="/nonexistent/python", trainer_workdir=tmp_path / "work", entry_script=script
    )
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        base_model_path=str(tmp_path / "base"),
    )
    with pytest.raises(SubprocessTrainerError, match="is not strictly inside"):
        await trainer.train([DPOPair(prompt="p", chosen="c", rejected="r", system="s")], config)
    assert "KAINE_STATE_KEY" not in seen_env
