# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-module JSON snapshot round-trips and a study-order revive chain."""

from __future__ import annotations

import asyncio
import json
import logging
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
from kaine.modules.affect import DimensionalState
from kaine.modules.affect.module import Affect
from kaine.modules.audition.module import Audition
from kaine.modules.effectors.module import Effectors
from kaine.modules.embodiment.module import Embodiment
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.interoception.module import Interoception
from kaine.modules.language.intent_log import IntentExpressionLog
from kaine.modules.language.module import Language
from kaine.modules.perceptual_locus.module import PerceptualLocus
from kaine.modules.planning.module import Planning
from kaine.modules.registry import ModuleRegistry
from kaine.modules.self_model.module import SelfModel, SelfModelDocument
from kaine.modules.sequence.anomaly import RollingZScoreAnomaly
from kaine.modules.sequence.featurizer import SnapshotFeaturizer
from kaine.modules.sequence.module import Sequence
from kaine.modules.sequence.rumination import RecurrenceRuminationDetector
from kaine.modules.sleep import VoiceAlignmentConfig
from kaine.modules.sleep.module import Sleep
from kaine.modules.social_cognition.agent import AgentModel
from kaine.modules.social_cognition.module import SocialCognition
from kaine.modules.social_cognition.store import InMemoryAgentStore
from kaine.modules.vision.module import Vision
from kaine.modules.vocal.module import Vocal
from kaine.modules.world_model.module import WorldModel
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

# ---------------------------------------------------------------------------
# Fixtures / lightweight test doubles
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    # Same pool size as the production bus client (redis-py 8 caps an unset
    # pool at 100).
    client = fakeredis.FakeRedis(
        decode_responses=True, max_connections=BusConfig().max_connections
    )
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

    def matches_state_shape(self, data: dict[str, Any]) -> bool:
        # The fake has no tensor shapes; any dict it produced fits it.
        return isinstance(data, dict)


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

    async def close(self) -> None:
        """The embodiment module closes its adapter on shutdown; the double has nothing to release."""


def _json_roundtrip(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


# ---------------------------------------------------------------------------
# Part A — every module's snapshot survives a JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roundtrip_interoception(bus: AsyncBus, tmp_path: Path) -> None:
    fwd = _FakeForwardModel({"weights": [9.0, 8.0]})
    m1 = Interoception(
        bus,
        reader=_FakeMetricsReader(),
        forward_model=fwd,
        entity_clock=EntityClock(),
    )
    m1._cycle_cursor = "160-0"
    m1._read_interval_s = 2.5
    state = _json_roundtrip(m1.serialize())
    m2 = Interoception(
        bus,
        reader=_FakeMetricsReader(),
        forward_model=_FakeForwardModel(),
        entity_clock=EntityClock(),
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_sequence(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Sequence(
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
    m2 = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=_FakeNetwork(units=4),
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    want = dict(state)
    for key in ("last_interaction_at", "time_since_last_interaction_s"):
        g = got.pop(key)
        w = want.pop(key)
        assert g == pytest.approx(w, abs=10.0)  # CI runners can take seconds between save and restore
    assert got == want


@pytest.mark.asyncio
async def test_roundtrip_vision(bus: AsyncBus, tmp_path: Path) -> None:
    enc = _FakeEncoder(model_id="roundtrip-encoder")
    m1 = Vision(
        bus,
        encoder=enc,
        forward_prediction=False,
        change_alert_threshold=1e-4,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    state = _json_roundtrip(m1.serialize())
    m2 = Vision(
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
async def test_roundtrip_language(bus: AsyncBus, tmp_path: Path) -> None:
    log_path = tmp_path / "lingua" / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    m1 = Language(
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
    m2 = Language(
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
async def test_roundtrip_affect(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Affect(bus, publish_interval_s=0.5, clock=lambda: 0.0)
    m1._state = DimensionalState(valence=0.5, arousal=0.6, dominance=0.1)
    m1._baseline = DimensionalState(valence=0.1, arousal=0.3, dominance=0.0)
    m1._familiarity_cache = {"operator": 0.8}
    m1._goals.add("test goal", priority=0.5)
    state = _json_roundtrip(m1.serialize())
    m2 = Affect(bus, publish_interval_s=0.5, clock=lambda: 0.0)
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_episodic_memory(bus: AsyncBus, tmp_path: Path) -> None:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    core = EpisodicMemoryCore(
        embedder=emb,
        storage=InMemoryStorage(latent_dim=emb.latent_dim),
        short_term_capacity=8,
    )
    m1 = EpisodicMemory(bus, core=core)
    # Synchronous serialize() is metadata-only; the matching deserialize is a
    # no-op unless a memory_state capture is present (Mnemos.deserialize docstring).
    state = _json_roundtrip(m1.serialize())
    m2 = EpisodicMemory(
        bus,
        core=EpisodicMemoryCore(
            embedder=FakeEmbedder(latent_dim=8),
            storage=InMemoryStorage(latent_dim=8),
            short_term_capacity=8,
        ),
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_sleep(bus: AsyncBus, tmp_path: Path) -> None:
    intent_log = tmp_path / "hypnos" / "intent.jsonl"
    adapter_dir = tmp_path / "hypnos" / "adapters"
    intent_log.parent.mkdir(parents=True, exist_ok=True)
    adapter_dir.mkdir(parents=True, exist_ok=True)
    m1 = Sleep(
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
    m2 = Sleep(
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
async def test_roundtrip_world_model(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = WorldModel(bus, backend="fake")
    m1._training_enabled = True
    state = _json_roundtrip(m1.serialize())
    m2 = WorldModel(bus, backend="fake")
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    # These keys are echoed configuration; the configured checkpoint path wins.
    fresh = WorldModel(bus, backend="fake")
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
async def test_roundtrip_planning(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Planning(bus, engine=_FakeEngine())
    m1._last_action = "move"
    m1._last_posterior = [[0.2, 0.8], [0.5, 0.5]]
    state = _json_roundtrip(m1.serialize())
    m2 = Planning(bus, engine=_FakeEngine())
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_self_model(bus: AsyncBus, tmp_path: Path) -> None:
    p = tmp_path / "eidolon.json"
    m1 = SelfModel(bus, persistence_path=p, save_interval_s=60)
    m1._model = SelfModelDocument(name="Aria", values=["honesty", "curiosity"])
    m1._drift_count = 7
    m1._internal_cursor = "5-0"
    m1._external_cursor = "9-0"
    state = _json_roundtrip(m1.serialize())
    m2 = SelfModel(bus, persistence_path=tmp_path / "eidolon2.json", save_interval_s=60)
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_social_cognition(bus: AsyncBus, tmp_path: Path) -> None:
    store = InMemoryAgentStore()
    m1 = SocialCognition(bus, store=store)
    model = AgentModel(id="operator", label="operator", interaction_count=5)
    profiles = {model.id: model.to_dict()}
    m1._store.deserialize(json.dumps(profiles).encode("utf-8"))
    state = _json_roundtrip(m1.serialize())
    m2 = SocialCognition(bus, store=InMemoryAgentStore())
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_vocal(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Vocal(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / "vox",
    )
    m1._current_state = DimensionalState(valence=0.5, arousal=0.7, dominance=-0.2)
    m1._voice_mode = "cloned"
    state = _json_roundtrip(m1.serialize())
    m2 = Vocal(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / "vox2",
    )
    m2.deserialize(state)
    got = _json_roundtrip(m2.serialize())
    # voice_mode is echoed configuration, not restored state.
    fresh = Vocal(
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
async def test_roundtrip_effectors(bus: AsyncBus, tmp_path: Path) -> None:
    m1 = Effectors(
        bus,
        sandbox_path=tmp_path / "sb",
        audit_log_path=tmp_path / "audit.log",
        enabled_effectors=["file_write"],
    )
    state = _json_roundtrip(m1.serialize())
    m2 = Effectors(
        bus,
        sandbox_path=tmp_path / "sb2",
        audit_log_path=tmp_path / "audit2.log",
        enabled_effectors=["file_write"],
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_perceptual_locus(bus: AsyncBus, tmp_path: Path) -> None:
    p = tmp_path / "desired.json"
    m1 = PerceptualLocus(
        bus,
        allow_self_switch=True,
        min_dwell_s=0.0,
        desired_path=p,
    )
    m1._inhibited = True
    state = _json_roundtrip(m1.serialize())
    m2 = PerceptualLocus(
        bus,
        allow_self_switch=True,
        min_dwell_s=0.0,
        desired_path=tmp_path / "desired2.json",
    )
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


@pytest.mark.asyncio
async def test_roundtrip_embodiment(bus: AsyncBus, tmp_path: Path) -> None:
    adapter = _FakeAdapter()
    m1 = Embodiment(bus, adapter=adapter, enabled=True)
    m1._intent_cursor = "42-0"
    m1._speech_cursor = "99-0"
    state = _json_roundtrip(m1.serialize())
    m2 = Embodiment(bus, adapter=_FakeAdapter(), enabled=True)
    m2.deserialize(state)
    assert _json_roundtrip(m2.serialize()) == state


# ---------------------------------------------------------------------------
# Part B — study-order revive chain
# ---------------------------------------------------------------------------


async def _build_interoception(bus: AsyncBus, tmp_path: Path, name: str) -> Interoception:
    m = Interoception(
        bus,
        reader=_FakeMetricsReader(),
        forward_model=_FakeForwardModel(),
        entity_clock=EntityClock(),
    )
    await m.initialize()
    return m


async def _build_sequence(bus: AsyncBus, tmp_path: Path, name: str) -> Sequence:
    m = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=_FakeNetwork(units=4),
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    await m.initialize()
    return m


async def _build_vision(bus: AsyncBus, tmp_path: Path, name: str) -> Vision:
    m = Vision(
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


async def _build_language(bus: AsyncBus, tmp_path: Path, name: str) -> Language:
    log_path = tmp_path / name / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    m = Language(
        bus,
        chat_client=_FakeChatClient(),
        intent_log=IntentExpressionLog(log_path),
        model_id="base",
    )
    await m.initialize()
    return m


async def _build_affect(bus: AsyncBus, tmp_path: Path, name: str) -> Affect:
    m = Affect(bus, publish_interval_s=0.5, clock=lambda: 0.0)
    await m.initialize()
    return m


async def _build_episodic_memory(bus: AsyncBus, tmp_path: Path, name: str) -> EpisodicMemory:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(
        embedder=emb,
        storage=storage,
        short_term_capacity=8,
    )
    m = EpisodicMemory(bus, core=core)
    await m.initialize()
    return m


async def _build_sleep(bus: AsyncBus, tmp_path: Path, name: str) -> Sleep:
    intent_log = tmp_path / name / "intent.jsonl"
    adapter_dir = tmp_path / name / "adapters"
    intent_log.parent.mkdir(parents=True, exist_ok=True)
    adapter_dir.mkdir(parents=True, exist_ok=True)
    m = Sleep(
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


async def _build_world_model(bus: AsyncBus, tmp_path: Path, name: str) -> WorldModel:
    m = WorldModel(bus, backend="fake")
    await m.initialize()
    return m


async def _build_planning(bus: AsyncBus, tmp_path: Path, name: str) -> Planning:
    m = Planning(bus, engine=_FakeEngine())
    await m.initialize()
    return m


async def _build_self_model(bus: AsyncBus, tmp_path: Path, name: str) -> SelfModel:
    p = tmp_path / f"{name}.json"
    m = SelfModel(bus, persistence_path=p, save_interval_s=60)
    await m.initialize()
    return m


async def _build_social_cognition(bus: AsyncBus, tmp_path: Path, name: str) -> SocialCognition:
    m = SocialCognition(bus, store=InMemoryAgentStore())
    await m.initialize()
    return m


async def _build_vocal(bus: AsyncBus, tmp_path: Path, name: str) -> Vocal:
    m = Vocal(
        bus,
        tts_client=_FakeTTSClient(),
        player=_FakePlayer(),
        sink_path=tmp_path / name,
    )
    await m.initialize()
    return m


async def _build_effectors(bus: AsyncBus, tmp_path: Path, name: str) -> Effectors:
    m = Effectors(
        bus,
        sandbox_path=tmp_path / name / "sb",
        audit_log_path=tmp_path / name / "audit.log",
        enabled_effectors=["file_write"],
    )
    await m.initialize()
    return m


async def _build_perceptual_locus(bus: AsyncBus, tmp_path: Path, name: str) -> PerceptualLocus:
    p = tmp_path / name / "desired.json"
    m = PerceptualLocus(
        bus,
        allow_self_switch=True,
        min_dwell_s=0.0,
        desired_path=p,
    )
    await m.initialize()
    return m


async def _build_embodiment(bus: AsyncBus, tmp_path: Path, name: str) -> Embodiment:
    m = Embodiment(bus, adapter=_FakeAdapter(), enabled=True)
    await m.initialize()
    return m


BASE_FACTORIES: dict[str, Any] = {
    "soma": _build_interoception,
    "chronos": _build_sequence,
    "topos": _build_vision,
    "audition": _build_audition,
    "lingua": _build_language,
}

ORDER: list[tuple[str, Any]] = [
    ("thymos", _build_affect),
    ("mnemos", _build_episodic_memory),
    ("hypnos", _build_sleep),
    ("phantasia", _build_world_model),
    ("nous", _build_planning),
    ("eidolon", _build_self_model),
    ("empatheia", _build_social_cognition),
    ("vox", _build_vocal),
    ("praxis", _build_effectors),
    ("perception", _build_perceptual_locus),
    ("mundus", _build_embodiment),
]


def _mutate_interoception(m: Interoception, i: int) -> None:
    m._cycle_cursor = f"step-{i}"
    m._read_interval_s = 1.0 + i * 0.1


def _mutate_sequence(m: Sequence, i: int) -> None:
    m._last_interaction_at = 1000.0 + i
    # Keep the default "audition.out" cursor that deserialize preserves.
    m._user_input_cursors["lingua.external"] = f"{i}-0"
    m._user_input_cursors["volition.out"] = f"{i + 1}-0"


def _mutate_vision(m: Vision, i: int) -> None:
    # The vision module's serialize() is config/encoder-id only; no mutable snapshot state.
    pass


def _mutate_audition(m: Audition, i: int) -> None:
    m._stt_model = f"stt-{i}"


def _mutate_language(m: Language, i: int) -> None:
    m._model_id = f"lingua-{i}"
    m._temperature = 0.5 + i * 0.05
    m._intent_cursor = f"{i}-0"


def _mutate_affect(m: Affect, i: int) -> None:
    m._state = DimensionalState(
        valence=0.1 * i, arousal=0.3 + 0.05 * i, dominance=0.0
    )
    m._baseline = DimensionalState(valence=0.0, arousal=0.3, dominance=0.0)
    m._familiarity_cache = {f"agent-{i}": 0.1 * i}
    m._goals.add(f"goal {i}", priority=0.5)


async def _mutate_episodic_memory(m: EpisodicMemory, i: int) -> None:
    await m._core.store(f"memory {i}")


def _mutate_sleep(m: Sleep, i: int) -> None:
    m._last_sleep_at = 5000.0 + i


def _mutate_world_model(m: WorldModel, i: int) -> None:
    m._training_enabled = True


def _mutate_planning(m: Planning, i: int) -> None:
    m._last_action = f"act-{i}"
    m._last_posterior = [[0.1 * i, 1.0 - 0.1 * i]]


def _mutate_self_model(m: SelfModel, i: int) -> None:
    m._model = SelfModelDocument(name=f"Eid{i}", values=[f"v{i}"])
    m._drift_count = i


async def _mutate_social_cognition(m: SocialCognition, i: int) -> None:
    agent = AgentModel(id=f"agent-{i}", label=f"agent-{i}", interaction_count=i)
    profiles = {agent.id: agent.to_dict()}
    m._store.deserialize(json.dumps(profiles).encode("utf-8"))


def _mutate_vocal(m: Vocal, i: int) -> None:
    # Keep every dimension inside its clamp range so the round-trip is exact.
    m._current_state = DimensionalState(
        valence=0.05 * i, arousal=0.08 * i, dominance=-0.05 * i
    )
    m._voice_mode = f"mode-{i}"


def _mutate_effectors(m: Effectors, i: int) -> None:
    # The effectors module's serialize() returns the fixed effector set only.
    pass


def _mutate_perceptual_locus(m: PerceptualLocus, i: int) -> None:
    m._inhibited = True


def _mutate_embodiment(m: Embodiment, i: int) -> None:
    m._intent_cursor = f"{i}-0"
    m._speech_cursor = f"{i + 1}-0"


MUTATORS: dict[str, Any] = {
    "soma": _mutate_interoception,
    "chronos": _mutate_sequence,
    "topos": _mutate_vision,
    "audition": _mutate_audition,
    "lingua": _mutate_language,
    "thymos": _mutate_affect,
    "mnemos": _mutate_episodic_memory,
    "hypnos": _mutate_sleep,
    "phantasia": _mutate_world_model,
    "nous": _mutate_planning,
    "eidolon": _mutate_self_model,
    "empatheia": _mutate_social_cognition,
    "vox": _mutate_vocal,
    "praxis": _mutate_effectors,
    "perception": _mutate_perceptual_locus,
    "mundus": _mutate_embodiment,
}


def _comparable_state(name: str, state: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot dict normalised for comparison after revive.

    The sequence module merges default cursors, so inject the default that revive adds.
    the audition, vocal and world model modules echo configuration into the snapshot but a revived
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
    monkeypatch.setattr(_stage, "STAGE_PATH", tmp_path / "stage.json")

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
                # Teardown is best effort: stand-in collaborators may fail to
                # shut down cleanly, and one failure must not skip the rest.
                logging.getLogger(__name__).warning(
                    "teardown: %s shutdown failed", type(m).__name__, exc_info=True
                )

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
                elif n == "chronos":
                    for key in ("last_interaction_at", "time_since_last_interaction_s"):
                        g = got.pop(key, None)
                        w = want.pop(key, None)
                        assert (g is None and w is None) or g == pytest.approx(w, abs=10.0)  # the revive chain runs for seconds on slow CI runners
                    assert got == want, f"step {i} module {n} mismatch"
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
                # A fresh self-model module draws a launch name (generate_launch_name), so
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
