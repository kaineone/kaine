# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import dataclasses
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from kaine.cycle.individuation_probe import ProbeFailure
from kaine.cycle.individuation_producer import (
    IndividuationCore,
    ProducerSettings,
)
from kaine.lifecycle.individuation_stats import spending_alpha
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    IndividuationStoreError,
    ProbeSample,
    conditioning_digest,
    load_ledger,
    load_reference,
    save_ledger,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

pytestmark = pytest.mark.asyncio

BATTERY = [
    "What is your name and purpose?",
    "Describe a value you would never compromise.",
    "How do you see yourself changing over time?",
]

CONDITIONS = {
    "model_id": "test-model",
    "temperature": 0.7,
    "max_tokens": 160,
    "think": False,
    "persona_version": "1",
    "persona_name": "test-persona",
    "embedder_id": "fake-embed",
    "embedder_dim": 16,
    "server_build": "test-build",
}


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class FakeSampler:
    def __init__(self, variant: str = "birth", failure_call: int | None = None):
        self.variant = variant
        self.failure_call = failure_call
        self.calls = 0

    async def __call__(self, prompt: str, seed: int) -> ProbeSample | ProbeFailure:
        self.calls += 1
        if self.failure_call is not None and self.calls == self.failure_call:
            return ProbeFailure("request_failed")
        return ProbeSample(
            text=f"{prompt}|{self.variant}|{seed}",
            seed=seed,
            finish_reason="stop",
            completion_tokens=5,
        )


class FakeEmbed:
    def __init__(self, raise_on_call: int | None = None):
        self.raise_on_call = raise_on_call
        self.calls = 0

    async def __call__(self, text: str) -> list[float]:
        self.calls += 1
        if self.raise_on_call is not None and self.calls == self.raise_on_call:
            raise RuntimeError("embedding failed")
        parts = text.split("|")
        prompt, variant, seed_str = parts[0], parts[1], parts[2]
        centre_rng = np.random.default_rng(
            abs(hash(prompt + variant)) % 2**32
        )
        if variant == "drifted":
            centre = centre_rng.normal(5.0, 1.0, 16)
        else:
            centre = centre_rng.normal(0.0, 1.0, 16)
        noise_rng = np.random.default_rng(int(seed_str))
        noise = noise_rng.normal(0.0, 0.01, 16)
        return (centre + noise).tolist()


class FakeConditioning:
    def __init__(
        self,
        sha: str = "sha1",
        values: list[str] | None = None,
        norms: list[str] | None = None,
        second_sha: str | None = None,
        second_values: list[str] | None = None,
        second_norms: list[str] | None = None,
    ):
        self.calls = 0
        # Optional adapter sha per call; the last one repeats.
        self.sequence: list[str] | None = None
        self.first = (
            sha,
            list(values or ["value1"]),
            list(norms or ["norm1"]),
        )
        self.second = (
            second_sha if second_sha is not None else sha,
            list(second_values)
            if second_values is not None
            else list(self.first[1]),
            list(second_norms)
            if second_norms is not None
            else list(self.first[2]),
        )

    def __call__(self) -> tuple[str | None, list[str], list[str]]:
        self.calls += 1
        if self.sequence is not None:
            sha = self.sequence[min(self.calls, len(self.sequence)) - 1]
            return (sha, list(self.first[1]), list(self.first[2]))
        # A capture reads twice (before and after sampling).
        if self.calls <= 2:
            return self.first
        return self.second


class FakeAbort:
    def __init__(self, reason: str | None = None):
        self.reason = reason

    def __call__(self) -> str | None:
        return self.reason


class FixedNow:
    def __init__(self, ts: str = "2026-01-01T01:00:00+00:00"):
        self._dt = datetime.fromisoformat(ts)

    def __call__(self) -> datetime:
        return self._dt


class FakeSink:
    def __init__(self, raise_on: str | None = None):
        self.writes: list[dict] = []
        self.raise_on = raise_on

    async def write(self, report: dict) -> None:
        if self.raise_on and report.get("outcome") == self.raise_on:
            raise RuntimeError("sink failure")
        self.writes.append(report)


class FakePublish:
    def __init__(self):
        self.published: list[dict] = []

    async def __call__(self, payload: dict) -> None:
        self.published.append(payload)


def make_core(tmp_path: Path, **kwargs: object) -> tuple[IndividuationCore, IndividuationPaths]:
    paths = IndividuationPaths(root=tmp_path / "individuation")
    settings = kwargs.pop("settings", ProducerSettings(n_reference=6, n_current=4))
    defaults = {
        "paths": paths,
        "settings": settings,
        "battery": BATTERY,
        "sampler": FakeSampler(),
        "embed": FakeEmbed(),
        "embedder_id": "fake-embed",
        "conditions": lambda: CONDITIONS,
        "conditioning_inputs": FakeConditioning(),
        "born_at": lambda: "2026-01-01T00:00:00+00:00",
        "birth_adapter_file": lambda: None,
        "report_sink": FakeSink(),
        "publish": FakePublish(),
        "abort_reason": FakeAbort(),
        "rng": np.random.default_rng(0),
        "now": FixedNow(),
        "entity_name": "test",
    }
    defaults.update(kwargs)
    return IndividuationCore(**defaults), paths


async def test_capture_reference(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    conditioning = FakeConditioning(
        sha="sha-a", values=["v1", "v2"], norms=["n1"]
    )
    core, paths = make_core(tmp_path, sampler=sampler, conditioning_inputs=conditioning)

    doc, reason = await core.capture_reference("birth")
    assert reason is None
    assert doc is not None
    assert doc.reference_kind == "birth"
    assert len(doc.battery) == 3
    assert len(doc.samples) == 3
    assert all(len(prompt) == 6 for prompt in doc.samples)
    assert sampler.calls == 18

    loaded = load_reference(paths)
    assert loaded is not None
    assert loaded.reference_id == doc.reference_id
    assert loaded.conditions == CONDITIONS
    assert loaded.born_at == "2026-01-01T00:00:00+00:00"

    ledger = load_ledger(paths)
    assert ledger is not None
    assert ledger.reference_id == doc.reference_id
    assert ledger.looks_completed == 0
    expected_digest = conditioning_digest(
        adapter_sha="sha-a", values=["v1", "v2"], norms=["n1"]
    )
    assert ledger.last_look_conditions_digest == expected_digest


async def test_capture_failure(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth", failure_call=5)
    core, paths = make_core(tmp_path, sampler=sampler)

    doc, reason = await core.capture_reference("birth")
    assert doc is None
    assert reason == "request_failed"
    assert not paths.reference.exists()
    assert not paths.ledger.exists()


async def test_capture_abort(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    core, paths = make_core(
        tmp_path, sampler=sampler, abort_reason=FakeAbort("asleep")
    )

    doc, reason = await core.capture_reference("birth")
    assert doc is None
    assert reason == "asleep"
    assert sampler.calls == 0


async def test_unchanged_being(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    core, paths = make_core(tmp_path, sampler=sampler, report_sink=sink)

    await core.capture_reference("birth")
    outcome = await core.look(
        warmed_up=True, lived_seconds=100.0, lived_ticks=50
    )
    assert outcome.outcome == "skipped"
    assert outcome.reason == "unchanged"
    assert outcome.report is None
    assert not sink.writes
    assert sampler.calls == 18


async def test_scored_no_drift(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    pub = FakePublish()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    outcome = await core.look(
        warmed_up=True, lived_seconds=200.0, lived_ticks=100
    )

    assert outcome.outcome == "scored"
    assert outcome.reason is None
    assert outcome.significant is False
    assert outcome.effect_size_h is not None

    ledger = load_ledger(paths)
    assert ledger.looks_completed == 1
    assert ledger.alpha_spent == pytest.approx(spending_alpha(1, 0.05))
    assert ledger.individuated is False

    assert len(sink.writes) == 1
    assert sink.writes[0]["outcome"] == "scored"
    assert sink.writes[0]["significant"] is False
    assert sink.writes[0]["latched"] is False

    assert len(pub.published) == 1
    assert pub.published[0]["significant"] is False


async def test_scored_strong_drift(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    pub = FakePublish()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    sampler.variant = "drifted"
    outcome = await core.look(
        warmed_up=True, lived_seconds=200.0, lived_ticks=100
    )

    assert outcome.outcome == "scored"
    assert outcome.significant is True

    ledger = load_ledger(paths)
    assert ledger.individuated is True
    assert ledger.latched_report_id is not None

    report = sink.writes[0]
    assert report["outcome"] == "scored"
    assert report["significant"] is True
    assert report["latched"] is True
    assert ledger.latched_report_id == report["report_id"]

    assert len(pub.published) == 1
    assert pub.published[0]["significant"] is True


async def test_not_warmed_up(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="drifted")
    sink = FakeSink()
    pub = FakePublish()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    outcome = await core.look(
        warmed_up=False, lived_seconds=200.0, lived_ticks=100
    )

    assert outcome.outcome == "scored"
    assert outcome.significant is False

    ledger = load_ledger(paths)
    assert ledger.looks_completed == 1
    assert ledger.individuated is False

    assert sink.writes[0]["significant"] is False
    assert pub.published[0]["significant"] is False


async def test_failure_mid_run(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    pub = FakePublish()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    await core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=100)
    pre_ledger = load_ledger(paths)

    sampler.failure_call = sampler.calls + 1
    conditioning2 = FakeConditioning(sha="sha-c", second_sha="sha-c")
    core2, _ = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning2,
    )

    outcome = await core2.look(
        warmed_up=True, lived_seconds=300.0, lived_ticks=150
    )
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "request_failed"

    post_ledger = load_ledger(paths)
    assert post_ledger == pre_ledger
    assert len(pub.published) == 1
    assert sink.writes[-1]["outcome"] == "inconclusive"


async def test_digest_change_mid_run(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    conditioning = FakeConditioning()
    # Capture reads a twice, the look reads b before and c after sampling.
    conditioning.sequence = ["sha-a", "sha-a", "sha-b", "sha-c"]
    core, paths = make_core(
        tmp_path, sampler=sampler, report_sink=sink, conditioning_inputs=conditioning
    )

    await core.capture_reference("birth")
    pre_ledger = load_ledger(paths)

    outcome = await core.look(
        warmed_up=True, lived_seconds=200.0, lived_ticks=100
    )
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditioning_changed_mid_run"

    post_ledger = load_ledger(paths)
    assert post_ledger == pre_ledger
    assert sink.writes[-1]["outcome"] == "inconclusive"
    assert sink.writes[-1]["inconclusive_reason"] == "conditioning_changed_mid_run"


async def test_embedding_failure(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    embed = FakeEmbed(raise_on_call=1)
    sink = FakeSink()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        embed=embed,
        report_sink=sink,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    pre_ledger = load_ledger(paths)

    outcome = await core.look(
        warmed_up=True, lived_seconds=200.0, lived_ticks=100
    )
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "embedding_failed"

    post_ledger = load_ledger(paths)
    assert post_ledger == pre_ledger
    assert sink.writes[-1]["outcome"] == "inconclusive"


async def test_alpha_unresolvable(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path, sampler=sampler, report_sink=sink, conditioning_inputs=conditioning
    )

    await core.capture_reference("birth")
    ledger = load_ledger(paths)
    ledger = dataclasses.replace(ledger, looks_completed=500)
    save_ledger(paths, ledger)
    pre_ledger = load_ledger(paths)
    calls_before = sampler.calls

    outcome = await core.look(
        warmed_up=True, lived_seconds=200.0, lived_ticks=100
    )
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "alpha_unresolvable"
    assert sampler.calls == calls_before

    post_ledger = load_ledger(paths)
    assert post_ledger.looks_completed == 500
    assert post_ledger == pre_ledger
    assert sink.writes[-1]["outcome"] == "inconclusive"


async def test_ledger_order(tmp_path: Path) -> None:
    sink = FakeSink(raise_on="scored")
    sampler = FakeSampler(variant="birth")
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    with pytest.raises(RuntimeError):
        await core.look(
            warmed_up=True, lived_seconds=200.0, lived_ticks=100
        )

    ledger = load_ledger(paths)
    assert ledger.looks_completed == 1
    assert not sink.writes


async def test_latched_stays_latched(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    pub = FakePublish()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    sampler.variant = "drifted"
    await core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=100)
    assert load_ledger(paths).individuated is True

    sampler.variant = "birth"
    conditioning2 = FakeConditioning(sha="sha-c", second_sha="sha-c")
    core2, _ = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning2,
    )
    outcome = await core2.look(
        warmed_up=True, lived_seconds=300.0, lived_ticks=150
    )
    assert outcome.outcome == "scored"
    assert outcome.significant is False

    ledger = load_ledger(paths)
    assert ledger.individuated is True
    assert ledger.looks_completed == 2
    assert sink.writes[-1]["latched"] is True
    assert len(pub.published) == 2


async def test_regeneration_keeps_ledger(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    pub = FakePublish()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning,
    )

    await core.capture_reference("birth")
    sampler.variant = "drifted"
    await core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=100)

    pre_ledger = load_ledger(paths)
    assert pre_ledger.individuated is True
    old_ref_id = pre_ledger.reference_id

    sampler.variant = "birth"
    conditioning2 = FakeConditioning(sha="sha-c")
    core2, _ = make_core(
        tmp_path,
        sampler=sampler,
        report_sink=sink,
        publish=pub,
        conditioning_inputs=conditioning2,
    )
    doc, reason = await core2.capture_reference("capture", regenerate=True)
    assert reason is None
    assert doc.reference_kind == "capture"
    assert doc.reference_id != old_ref_id

    post_ref = load_reference(paths)
    assert post_ref.reference_id == doc.reference_id

    post_ledger = load_ledger(paths)
    assert post_ledger.reference_id == doc.reference_id
    assert post_ledger.looks_completed == pre_ledger.looks_completed
    assert post_ledger.alpha_spent == pre_ledger.alpha_spent
    assert post_ledger.individuated is True
    assert post_ledger.latched_report_id == pre_ledger.latched_report_id


async def test_capture_conditioning_change_writes_nothing(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    conditioning = FakeConditioning()
    conditioning.sequence = ["sha-a", "sha-b"]
    adapter = tmp_path / "adapter.gguf"
    adapter.write_bytes(b"birth adapter")
    core, paths = make_core(
        tmp_path,
        sampler=sampler,
        conditioning_inputs=conditioning,
        birth_adapter_file=lambda: adapter,
    )

    doc, reason = await core.capture_reference("birth")
    assert doc is None
    assert reason == "conditioning_changed_mid_run"
    assert not paths.reference.exists()
    assert not paths.ledger.exists()
    assert not paths.birth_adapter.exists()


async def test_capture_copies_birth_adapter_only_for_birth(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter.gguf"
    adapter.write_bytes(b"birth adapter")
    core, paths = make_core(tmp_path, birth_adapter_file=lambda: adapter)
    await core.capture_reference("birth")
    assert paths.birth_adapter.read_bytes() == b"birth adapter"

    adapter.write_bytes(b"later adapter")
    doc, reason = await core.capture_reference("capture", regenerate=True)
    assert reason is None
    assert doc.reference_kind == "capture"
    assert paths.birth_adapter.read_bytes() == b"birth adapter"


async def test_capture_refuses_existing_reference_before_sampling(
    tmp_path: Path,
) -> None:
    sampler = FakeSampler(variant="birth")
    core, paths = make_core(tmp_path, sampler=sampler)
    first, _ = await core.capture_reference("birth")
    calls = sampler.calls

    with pytest.raises(IndividuationStoreError):
        await core.capture_reference("capture")
    assert sampler.calls == calls
    assert load_reference(paths).reference_id == first.reference_id


async def test_birth_regeneration_is_refused(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    core, paths = make_core(tmp_path, sampler=sampler)
    with pytest.raises(ValueError):
        await core.capture_reference("birth", regenerate=True)
    assert sampler.calls == 0


async def test_second_significant_look_keeps_the_first_latch(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path, sampler=sampler, report_sink=sink, conditioning_inputs=conditioning
    )
    await core.capture_reference("birth")
    sampler.variant = "drifted"
    await core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=100)
    first = load_ledger(paths)
    assert first.individuated is True

    conditioning2 = FakeConditioning(sha="sha-c", second_sha="sha-c")
    core2, _ = make_core(
        tmp_path, sampler=sampler, report_sink=sink, conditioning_inputs=conditioning2
    )
    outcome = await core2.look(warmed_up=True, lived_seconds=300.0, lived_ticks=150)
    assert outcome.significant is True

    second = load_ledger(paths)
    assert second.looks_completed == 2
    assert second.latched_report_id == first.latched_report_id
    assert second.latched_report_id != sink.writes[-1]["report_id"]


async def test_scored_look_advances_the_digest(tmp_path: Path) -> None:
    sampler = FakeSampler(variant="birth")
    sink = FakeSink()
    conditioning = FakeConditioning(sha="sha-a", second_sha="sha-b")
    core, paths = make_core(
        tmp_path, sampler=sampler, report_sink=sink, conditioning_inputs=conditioning
    )
    await core.capture_reference("birth")
    first = await core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=100)
    assert first.outcome == "scored"
    calls = sampler.calls

    again = await core.look(warmed_up=True, lived_seconds=250.0, lived_ticks=120)
    assert again.outcome == "skipped"
    assert sampler.calls == calls
    assert load_ledger(paths).looks_completed == 1
