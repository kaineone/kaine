# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-module JSON snapshot round-trips and a study-order revive chain."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import kaine.lifecycle.stage as _stage
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.entity_clock import EntityClock
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle import preservation
from kaine.lifecycle.manager import ForkManager
from kaine.modules.audition.module import Audition
from kaine.modules.chronos.anomaly import RollingZScoreAnomaly
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.chronos.rumination import RecurrenceRuminationDetector
from kaine.modules.eidolon.module import Eidolon, SelfModel
from kaine.modules.empatheia.agent import AgentModel
from kaine.modules.empatheia.module import Empatheia
from kaine.modules.empatheia.store import InMemoryAgentStore
from kaine.modules.hypnos import VoiceAlignmentConfig
from kaine.modules.hypnos.module import Hypnos
from kaine.modules.lingua.intent_log import IntentExpressionLog
from kaine.modules.lingua.module import Lingua
from kaine.modules.mnemos import FakeEmbedder, InMemoryStorage, Mnemos, MnemosCore
from kaine.modules.mundus.module import Mundus
from kaine.modules.nous.module import Nous
from kaine.modules.perception.module import PerceptionLocus
from kaine.modules.phantasia.module import Phantasia
from kaine.modules.praxis.module import Praxis
from kaine.modules.registry import ModuleRegistry
from kaine.modules.soma.module import Soma
from kaine.modules.thymos import DimensionalState
from kaine.modules.thymos.module import Thymos
from kaine.modules.topos.module import Topos
from kaine.modules.vox.module import Vox
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

# ---------------------------------------------------------------------------
# Fixtures / lightweight test doubles
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _plaintext_encryptor() -> None:
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context() -> None:
    set_run_context(
        RunContext(
            run_id="testrun0123456789",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


class _FakeMetricsReader:
    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def read(self) -> dict[str, Any]:
        return {}

    @property
    def cycle_latency_window(self) -> int:
        return 4


class _FakeForwardModel:
    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self._state: dict[str, Any] = state or {"weights": [0.1, 0.2]}

    def state_dict(self) -> dict[str, Any]:
        return dict(self._state)

    def load_state_dict(self, data: dict[str, Any]) -> None:
        self._state = {
            k: list(v) if isinstance(v, list) else v for k, v in data.items()
        }

    def buffer_summary(self) -> dict[str, Any]:
        return {"size": 0}


class _FakeNetwork:
    def __init__(self, units: int = 4) -> None:
        self.units = units


class _FakeEncoder:
    def __init__(self, model_id: str = "test-encoder") -> None:
        self.model_id = model_id
        self.clip_len = 1

    async def load(self) -> None:
        return None


class _FakeSTTClient:
    async def transcribe(self, *args: Any, **kwargs: Any) -> str:
        return ""


class _FakeEmotionClassifier:
    def __init__(self, model_id: str = "test-emotion") -> None:
        self.model_id = model_id

    async def classify(self, *args: Any, **kwargs: Any) -> Any:
        return None


class _FakeChatClient:
    async def chat(self, *args: Any, **kwargs: Any) -> str:
        return "hello"


class _FakeTTSClient:
    closed: bool = False

    async def synthesize(self, *args: Any, **kwargs: Any) -> bytes:
        return b""

    async def close(self) -> None:
        self.closed = True


class _FakePlayer:
    async def play(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def close(self) -> None:
        pass


class _FakeTrainer:
    async def train(self, *args: Any, **kwargs: Any) -> Any:
        return None


class _FakeEngine:
    def seed_posterior(self, posterior: list[list[float]]) -> bool:
        return True


class _FakeAdapter:
    def capabilities(self) -> Any:
        class _Caps:
            action_families = {"wave": True}
            continuous_channels = ("head",)

        return _Caps()


def _json_roundtrip(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


# ---------------------------------------------------------------------------
# Part A — every module's snapshot survives a JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roundtrip_soma(bus: AsyncBus, tmp_path: Path) -> None:
    fwd = _FakeForwardModel({"weights": [9.0, 8.0]})
    m1 = Soma(
        bus,
        reader=_FakeMetricsReader(),
        forward_model=fwd,
        entity_clock=EntityClock(),
    )
    m1._cycle_cursor = "160-0"
    m1._read_interval_s = 2.5
    state = _json_roundtrip(m1.serialize())
    m2 = Soma(
        bus,
        reader=_FakeMetricsReader(),
        forward_model=_FakeForwardModel(),
        entity_clock=EntityClock(),
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_chronos(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=_FakeNetwork(units=4),
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    m1._last_interaction_at = 12345.6
    # Chronos.deserialize merges cursors, so keep the default "audition.out".
    m1._user_input_cursors.update(
        {"lingua.external": "99-0", "volition.out": "100-0"}
    )
    state = _json_roundtrip(m1.serialize())
    m2 = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=_FakeNetwork(units=4),
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_topos(bus: AsyncBus, tmp_path: Path) -> None:
    enc = _FakeEncoder(model_id="roundtrip-encoder")
    m1 = Topos(
        bus,
        encoder=enc,
        forward_prediction=False,
        change_alert_threshold=1e-4,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    state = _json_roundtrip(m1.serialize())
    m2 = Topos(
        bus,
        encoder=_FakeEncoder(model_id="roundtrip-encoder"),
        forward_prediction=False,
        change_alert_threshold=1e-4,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_audition(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Audition(
        bus,
        stt_client=_FakeSTTClient(),
        emotion_classifier=_FakeEmotionClassifier(model_id="audition-emo"),
        stt_model="fake-stt",
    )
    m1._stt_model = "custom-stt"
    m1._forward_model = _FakeForwardModel({"aud": [1.0, 2.0]})
    state = _json_roundtrip(m1.serialize())
    m2 = Audition(
        bus,
        stt_client=_FakeSTTClient(),
        emotion_classifier=_FakeEmotionClassifier(model_id="audition-emo"),
        stt_model="fake-stt",
    )
    m2._forward_model = _FakeForwardModel()
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    # stt_model and emotion_model_id are echoed configuration, not restored state.
    fresh = Audition(
        bus,
        stt_client=_FakeSTTClient(),
        emotion_classifier=_FakeEmotionClassifier(model_id="audition-emo"),
        stt_model="fake-stt",
    )
    assert got["stt_model"] == fresh._stt_model
    assert got["emotion_model_id"] == fresh._emotion_classifier.model_id
    for key in ("stt_model", "emotion_model_id"):
        state.pop(key, None)
        got.pop(key, None)
    assert got == state


@pytest.mark.asyncio
async def test_roundtrip_lingua(bus: AsyncBus, tmp_path: Path) -> None:
    log_path = tmp_path / "lingua" / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    m1 = Lingua(
        bus,
        chat_client=_FakeChatClient(),
        intent_log=IntentExpressionLog(log_path),
        model_id="lingua-roundtrip",
        temperature=0.9,
        max_tokens=128,
        think=True,
    )
    m1._intent_cursor = "7-0"
    state = _json_roundtrip(m1.serialize())
    m2 = Lingua(
        bus,
        chat_client=_FakeChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "lingua2" / "intent.jsonl"),
        model_id="lingua-roundtrip",
        temperature=0.9,
        max_tokens=128,
        think=True,
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_thymos(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Thymos(bus, publish_interval_s=0.5, clock=lambda: 0.0)
    m1._state = DimensionalState(valence=0.5, arousal=0.6, dominance=0.1)
    m1._baseline = DimensionalState(valence=0.1, arousal=0.3, dominance=0.0)
    m1._familiarity_cache = {"operator": 0.8}
    try:
        m1._goals.add("test goal", priority=0.5)  # type: ignore[union-attr]
    except AttributeError:
        pass
    state = _json_roundtrip(m1.serialize())
    m2 = Thymos(bus, publish_interval_s=0.5, clock=lambda: 0.0)
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_mnemos(bus: AsyncBus, tmp_path: Path) -> None:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    core = MnemosCore(
        embedder=emb,
        storage=InMemoryStorage(latent_dim=emb.latent_dim),
        short_term_capacity=8,
    )
    m1 = Mnemos(bus, core=core)
    # Synchronous serialize() is metadata-only; the matching deserialize is a
    # no-op unless a memory_state capture is present (Mnemos.deserialize docstring).
    state = _json_roundtrip(m1.serialize())
    m2 = Mnemos(
        bus,
        core=MnemosCore(
            embedder=FakeEmbedder(latent_dim=8),
            storage=InMemoryStorage(latent_dim=8),
            short_term_capacity=8,
        ),
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_hypnos(bus: AsyncBus, tmp_path: Path) -> None:
    intent_log = tmp_path / "hypnos" / "intent.jsonl"
    adapter_dir = tmp_path / "hypnos" / "adapters"
    intent_log.parent.mkdir(parents=True, exist_ok=True)
    adapter_dir.mkdir(parents=True, exist_ok=True)
    m1 = Hypnos(
        bus,
        trainer=_FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=intent_log,
            adapter_output_dir=adapter_dir,
            enabled=False,
        ),
        interval_seconds=60.0,
        max_deferral_seconds=10.0,
    )
    m1._last_sleep_at = 12345.0
    state = _json_roundtrip(m1.serialize())
    m2 = Hypnos(
        bus,
        trainer=_FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "hypnos2" / "intent.jsonl",
            adapter_output_dir=tmp_path / "hypnos2" / "adapters",
            enabled=False,
        ),
        interval_seconds=60.0,
        max_deferral_seconds=10.0,
    )
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    assert got["last_sleep_at"] == pytest.approx(state["last_sleep_at"])
    assert got["schedule"] == pytest.approx(state["schedule"], abs=1.0)
    # original_due_at / effective_due_at are old-process monotonic times and are
    # ignored on restore (Hypnos.deserialize docstring).


@pytest.mark.asyncio
async def test_roundtrip_phantasia(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Phantasia(bus, backend="fake")
    m1._training_enabled = True
    state = _json_roundtrip(m1.serialize())
    m2 = Phantasia(bus, backend="fake")
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    # These keys are echoed configuration; the configured checkpoint path wins.
    fresh = Phantasia(bus, backend="fake")
    fresh_state = _json_roundtrip(fresh.serialize())
    config_keys = (
        "backend",
        "checkpoint_path",
        "persist_weights",
        "training_enabled",
        "obs_dim",
        "encoder_version",
    )
    for key in config_keys:
        assert got[key] == fresh_state[key]
    for key in config_keys:
        state.pop(key, None)
        got.pop(key, None)
    assert got == state


@pytest.mark.asyncio
async def test_roundtrip_nous(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Nous(bus, engine=_FakeEngine())
    m1._last_action = "move"
    m1._last_posterior = [[0.2, 0.8], [0.5, 0.5]]
    state = _json_roundtrip(m1.serialize())
    m2 = Nous(bus, engine=_FakeEngine())
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_eidolon(bus: AsyncBus, tmp_path: Path) -> None:
    p = tmp_path / "eidolon.json"
    m1 = Eidolon(bus, persistence_path=p, save_interval_s=60)
    m1._model = SelfModel(name="Aria", values=["honesty", "curiosity"])
    m1._drift_count = 7
    m1._internal_cursor = "5-0"
    m1._external_cursor = "9-0"
    state = _json_roundtrip(m1.serialize())
    m2 = Eidolon(bus, persistence_path=tmp_path / "eidolon2.json", save_interval_s=60)
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_empatheia(bus: AsyncBus, tmp_path: Path) -> None:
    store = InMemoryAgentStore()
    m1 = Empatheia(bus, store=store)
    model = AgentModel(id="operator", label="operator", interaction_count=5)
    profiles = {model.id: model.to_dict()}
    m1._store.deserialize(json.dumps(profiles).encode("utf-8"))
    state = _json_roundtrip(m1.serialize())
    m2 = Empatheia(bus, store=InMemoryAgentStore())
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_vox(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Vox(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / "vox",
    )
    m1._current_state = DimensionalState(valence=0.5, arousal=0.7, dominance=-0.2)
    m1._voice_mode = "cloned"
    state = _json_roundtrip(m1.serialize())
    m2 = Vox(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / "vox2",
    )
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    # voice_mode is echoed configuration, not restored state.
    fresh = Vox(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / "vox3",
    )
    assert got["voice_mode"] == fresh._voice_mode
    state.pop("voice_mode", None)
    got.pop("voice_mode", None)
    assert got == state


@pytest.mark.asyncio
async def test_roundtrip_praxis(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Praxis(
        bus,
        sandbox_path=tmp_path / "sb",
        audit_log_path=tmp_path / "audit.log",
        enabled_effectors=["file_write"],
    )
    state = _json_roundtrip(m1.serialize())
    m2 = Praxis(
        bus,
        sandbox_path=tmp_path / "sb2",
        audit_log_path=tmp_path / "audit2.log",
        enabled_effectors=["file_write"],
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_perception(bus: AsyncBus, tmp_path: Path) -> None:
    p = tmp_path / "desired.json"
    m1 = PerceptionLocus(
        bus,
        allow_self_switch=True,
        min_dwell_s=0.0,
        desired_path=p,
    )
    m1._inhibited = True
    state = _json_roundtrip(m1.serialize())
    m2 = PerceptionLocus(
        bus,
        allow_self_switch=True,
        min_dwell_s=0.0,
        desired_path=tmp_path / "desired2.json",
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_mundus(bus: AsyncBus, tmp_path: Path) -> None:
    adapter = _FakeAdapter()
    m1 = Mundus(bus, adapter=adapter, enabled=True)
    m1._intent_cursor = "42-0"
    m1._speech_cursor = "99-0"
    state = _json_roundtrip(m1.serialize())
    m2 = Mundus(bus, adapter=_FakeAdapter(), enabled=True)
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


# ---------------------------------------------------------------------------
# Part B — study-order revive chain
# ---------------------------------------------------------------------------


async def _build_soma(bus: AsyncBus, tmp_path: Path, name: str) -> Soma:
    m = Soma(
        bus,
        reader=_FakeMetricsReader(),
        forward_model=_FakeForwardModel(),
        entity_clock=EntityClock(),
    )
    await m.initialize()
    return m


async def _build_chronos(bus: AsyncBus, tmp_path: Path, name: str) -> Chronos:
    m = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=_FakeNetwork(units=4),
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    await m.initialize()
    return m


async def _build_topos(bus: AsyncBus, tmp_path: Path, name: str) -> Topos:
    m = Topos(
        bus,
        encoder=_FakeEncoder(),
        forward_prediction=False,
        change_alert_threshold=1e-4,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    await m.initialize()
    return m


async def _build_audition(bus: AsyncBus, tmp_path: Path, name: str) -> Audition:
    m = Audition(
        bus,
        stt_client=_FakeSTTClient(),
        emotion_classifier=_FakeEmotionClassifier(model_id="aud-emo"),
        stt_model="fake-stt",
    )
    m._forward_model = _FakeForwardModel()
    await m.initialize()
    return m


async def _build_lingua(bus: AsyncBus, tmp_path: Path, name: str) -> Lingua:
    log_path = tmp_path / name / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    m = Lingua(
        bus,
        chat_client=_FakeChatClient(),
        intent_log=IntentExpressionLog(log_path),
        model_id="base",
    )
    await m.initialize()
    return m


async def _build_thymos(bus: AsyncBus, tmp_path: Path, name: str) -> Thymos:
    m = Thymos(bus, publish_interval_s=0.5, clock=lambda: 0.0)
    await m.initialize()
    return m


async def _build_mnemos(bus: AsyncBus, tmp_path: Path, name: str) -> Mnemos:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = MnemosCore(
        embedder=emb,
        storage=storage,
        short_term_capacity=8,
    )
    m = Mnemos(bus, core=core)
    await m.initialize()
    return m


async def _build_hypnos(bus: AsyncBus, tmp_path: Path, name: str) -> Hypnos:
    intent_log = tmp_path / name / "intent.jsonl"
    adapter_dir = tmp_path / name / "adapters"
    intent_log.parent.mkdir(parents=True, exist_ok=True)
    adapter_dir.mkdir(parents=True, exist_ok=True)
    m = Hypnos(
        bus,
        trainer=_FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=intent_log,
            adapter_output_dir=adapter_dir,
            enabled=False,
        ),
        interval_seconds=60.0,
        max_deferral_seconds=10.0,
    )
    await m.initialize()
    return m


async def _build_phantasia(bus: AsyncBus, tmp_path: Path, name: str) -> Phantasia:
    m = Phantasia(bus, backend="fake")
    await m.initialize()
    return m


async def _build_nous(bus: AsyncBus, tmp_path: Path, name: str) -> Nous:
    m = Nous(bus, engine=_FakeEngine())
    await m.initialize()
    return m


async def _build_eidolon(bus: AsyncBus, tmp_path: Path, name: str) -> Eidolon:
    p = tmp_path / f"{name}.json"
    m = Eidolon(bus, persistence_path=p, save_interval_s=60)
    await m.initialize()
    return m


async def _build_empatheia(bus: AsyncBus, tmp_path: Path, name: str) -> Empatheia:
    m = Empatheia(bus, store=InMemoryAgentStore())
    await m.initialize()
    return m


async def _build_vox(bus: AsyncBus, tmp_path: Path, name: str) -> Vox:
    m = Vox(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / name,
    )
    await m.initialize()
    return m


async def _build_praxis(bus: AsyncBus, tmp_path: Path, name: str) -> Praxis:
    m = Praxis(
        bus,
        sandbox_path=tmp_path / name / "sb",
        audit_log_path=tmp_path / name / "audit.log",
        enabled_effectors=["file_write"],
    )
    await m.initialize()
    return m


async def _build_perception(bus: AsyncBus, tmp_path: Path, name: str) -> PerceptionLocus:
    p = tmp_path / name / "desired.json"
    m = PerceptionLocus(
        bus,
        allow_self_switch=True,
        min_dwell_s=0.0,
        desired_path=p,
    )
    await m.initialize()
    return m


async def _build_mundus(bus: AsyncBus, tmp_path: Path, name: str) -> Mundus:
    m = Mundus(bus, adapter=_FakeAdapter(), enabled=True)
    await m.initialize()
    return m


BASE_FACTORIES: dict[str, Any] = {
    "soma": _build_soma,
    "chronos": _build_chronos,
    "topos": _build_topos,
    "audition": _build_audition,
    "lingua": _build_lingua,
}

ORDER: list[tuple[str, Any]] = [
    ("thymos", _build_thymos),
    ("mnemos", _build_mnemos),
    ("hypnos", _build_hypnos),
    ("phantasia", _build_phantasia),
    ("nous", _build_nous),
    ("eidolon", _build_eidolon),
    ("empatheia", _build_empatheia),
    ("vox", _build_vox),
    ("praxis", _build_praxis),
    ("perception", _build_perception),
    ("mundus", _build_mundus),
]


def _mutate_soma(m: Soma, i: int) -> None:
    m._cycle_cursor = f"step-{i}"
    m._read_interval_s = 1.0 + i * 0.1


def _mutate_chronos(m: Chronos, i: int) -> None:
    m._last_interaction_at = 1000.0 + i
    # Keep the default "audition.out" cursor that deserialize preserves.
    m._user_input_cursors["lingua.external"] = f"{i}-0"
    m._user_input_cursors["volition.out"] = f"{i + 1}-0"


def _mutate_topos(m: Topos, i: int) -> None:
    # Topos serialize() is config/encoder-id only; no mutable snapshot state.
    pass


def _mutate_audition(m: Audition, i: int) -> None:
    m._stt_model = f"stt-{i}"


def _mutate_lingua(m: Lingua, i: int) -> None:
    m._model_id = f"lingua-{i}"
    m._temperature = 0.5 + i * 0.05
    m._intent_cursor = f"{i}-0"


def _mutate_thymos(m: Thymos, i: int) -> None:
    m._state = DimensionalState(
        valence=0.1 * i, arousal=0.3 + 0.05 * i, dominance=0.0
    )
    m._baseline = DimensionalState(valence=0.0, arousal=0.3, dominance=0.0)
    m._familiarity_cache = {f"agent-{i}": 0.1 * i}
    try:
        m._goals.add(f"goal {i}", priority=0.5)  # type: ignore[union-attr]
    except AttributeError:
        pass


async def _mutate_mnemos(m: Mnemos, i: int) -> None:
    await m._core.store(f"memory {i}")


def _mutate_hypnos(m: Hypnos, i: int) -> None:
    m._last_sleep_at = 5000.0 + i


def _mutate_phantasia(m: Phantasia, i: int) -> None:
    m._training_enabled = True


def _mutate_nous(m: Nous, i: int) -> None:
    m._last_action = f"act-{i}"
    m._last_posterior = [[0.1 * i, 1.0 - 0.1 * i]]


def _mutate_eidolon(m: Eidolon, i: int) -> None:
    m._model = SelfModel(name=f"Eid{i}", values=[f"v{i}"])
    m._drift_count = i


async def _mutate_empatheia(m: Empatheia, i: int) -> None:
    agent = AgentModel(id=f"agent-{i}", label=f"agent-{i}", interaction_count=i)
    profiles = {agent.id: agent.to_dict()}
    m._store.deserialize(json.dumps(profiles).encode("utf-8"))


def _mutate_vox(m: Vox, i: int) -> None:
    # Keep every dimension inside its clamp range so the round-trip is exact.
    m._current_state = DimensionalState(
        valence=0.05 * i, arousal=0.08 * i, dominance=-0.05 * i
    )
    m._voice_mode = f"mode-{i}"


def _mutate_praxis(m: Praxis, i: int) -> None:
    # Praxis serialize() returns the fixed effector set only.
    pass


def _mutate_perception(m: PerceptionLocus, i: int) -> None:
    m._inhibited = True


def _mutate_mundus(m: Mundus, i: int) -> None:
    m._intent_cursor = f"{i}-0"
    m._speech_cursor = f"{i + 1}-0"


MUTATORS: dict[str, Any] = {
    "soma": _mutate_soma,
    "chronos": _mutate_chronos,
    "topos": _mutate_topos,
    "audition": _mutate_audition,
    "lingua": _mutate_lingua,
    "thymos": _mutate_thymos,
    "mnemos": _mutate_mnemos,
    "hypnos": _mutate_hypnos,
    "phantasia": _mutate_phantasia,
    "nous": _mutate_nous,
    "eidolon": _mutate_eidolon,
    "empatheia": _mutate_empatheia,
    "vox": _mutate_vox,
    "praxis": _mutate_praxis,
    "perception": _mutate_perception,
    "mundus": _mutate_mundus,
}


def _comparable_state(name: str, state: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot dict normalised for comparison after revive.

    Chronos merges default cursors, so inject the default that revive adds.
    Audition/Vox/Phantasia echo configuration into the snapshot but a revived
    instance keeps its current configuration, so drop those keys.
    """
    s = _json_roundtrip(state)
    if name == "chronos":
        s.setdefault("user_input_cursors", {}).setdefault("audition.out", "$")
    elif name == "audition":
        s.pop("stt_model", None)
        s.pop("emotion_model_id", None)
    elif name == "vox":
        s.pop("voice_mode", None)
    elif name == "phantasia":
        for key in (
            "backend",
            "checkpoint_path",
            "persist_weights",
            "training_enabled",
            "obs_dim",
            "encoder_version",
        ):
            s.pop(key, None)
    return s


@pytest.mark.asyncio
async def test_study_order_revive_chain(
    bus: AsyncBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_stage, "STAGE_PATH", str(tmp_path / "stage"))

    out_root = tmp_path / "backups"
    forks = tmp_path / "forks"
    fm = ForkManager(forks)

    old_modules: dict[str, Any] = {}
    reg = ModuleRegistry()
    for name, factory in BASE_FACTORIES.items():
        m = await factory(bus, tmp_path, name)
        reg.register(m)
        old_modules[name] = m

    initialized: set[Any] = set(old_modules.values())

    async def _shutdown_all() -> None:
        for m in initialized:
            try:
                await m.shutdown()
            except Exception:
                pass

    try:
        for i, (name, factory) in enumerate(ORDER):
            new_mod = await factory(bus, tmp_path, name)
            reg.register(new_mod)
            old_modules[name] = new_mod
            initialized.add(new_mod)

            # Mutate every module that existed before this step.
            for prev_name, prev_mod in list(old_modules.items()):
                if prev_name == name:
                    continue
                mutator = MUTATORS[prev_name]
                if asyncio.iscoroutinefunction(mutator):
                    await mutator(prev_mod, i)
                else:
                    mutator(prev_mod, i)

            pre = {n: _json_roundtrip(m.serialize()) for n, m in old_modules.items()}

            result = await fm.preserve_live(
                reg,
                reason="chain",
                label=f"step{i}",
                out_root=out_root,
                entity_name="chain",
            )
            assert result.ok, f"step {i} preserve failed"
            bundle = out_root / f"preservation_{result.preservation_id}_chain"

            new_reg = ModuleRegistry()
            fresh_modules: dict[str, Any] = {}
            for n, f in BASE_FACTORIES.items():
                fresh_modules[n] = await f(bus, tmp_path, f"{n}_fresh")
                new_reg.register(fresh_modules[n])
                initialized.add(fresh_modules[n])
            for j in range(i + 1):
                n, f = ORDER[j]
                fresh_modules[n] = await f(bus, tmp_path, f"{n}_fresh")
                new_reg.register(fresh_modules[n])
                initialized.add(fresh_modules[n])

            await preservation.revive(bundle, new_reg)

            # Every previously captured module must match its pre-preservation state.
            for n in old_modules:
                if n == name:
                    continue
                got = _comparable_state(n, _json_roundtrip(fresh_modules[n].serialize()))
                want = _comparable_state(n, pre[n])
                if n == "hypnos":
                    assert got["last_sleep_at"] == pytest.approx(want["last_sleep_at"])
                    assert got["schedule"] == pytest.approx(want["schedule"], abs=1.0)
                else:
                    assert got == want, f"step {i} module {n} mismatch"

            # The newly added module must look like a fresh instance.
            fresh_new = await factory(bus, tmp_path, f"{name}_fresh_now")
            initialized.add(fresh_new)
            got_new = _comparable_state(
                name, _json_roundtrip(fresh_modules[name].serialize())
            )
            want_new = _comparable_state(name, _json_roundtrip(fresh_new.serialize()))
            if name == "hypnos":
                assert got_new["last_sleep_at"] == pytest.approx(want_new["last_sleep_at"])
                assert got_new["schedule"] == pytest.approx(
                    want_new["schedule"], abs=1.0
                )
            elif name == "eidolon":
                # A fresh Eidolon draws a launch name (generate_launch_name), so
                # two fresh instances differ only in the self-model's name.
                got_model = json.loads(got_new.pop("model"))
                want_model = json.loads(want_new.pop("model"))
                got_model.pop("name", None)
                want_model.pop("name", None)
                assert got_model == want_model, f"step {i} new module {name} mismatch"
                assert got_new == want_new, f"step {i} new module {name} mismatch"
            else:
                assert got_new == want_new, f"step {i} new module {name} mismatch"
    finally:
        await _shutdown_all()
