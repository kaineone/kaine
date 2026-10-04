# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import dataclasses

import pytest

from kaine.cycle.individuation_probe import ProbeFailure
from kaine.lifecycle.individuation_store import (
    IndividuationStoreError,
    ProbeSample,
    load_ledger,
    save_ledger,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_producer_core import (
    FakeConditioning,
    make_core,
)


def changing() -> FakeConditioning:
    """Conditioning that changes after the capture, so a look is due."""
    return FakeConditioning(sha="sha-a", second_sha="sha-b")


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class FirstTwoConditioning:
    """Returns valid conditioning twice, then raises."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> tuple[str | None, list[str], list[str]]:
        self.calls += 1
        if self.calls <= 2:
            return ("sha-a", ["v"], ["n"])
        raise RuntimeError("conditioning unreadable")


class RaisingConditioning:
    def __call__(self) -> tuple[str | None, list[str], list[str]]:
        raise RuntimeError("conditioning unreadable")


async def test_look_report_build_failure_keeps_ledger_unchanged(tmp_path):
    core, paths = make_core(
        tmp_path, entity_name="x" * 201, conditioning_inputs=changing()
    )
    await core.capture_reference("birth")
    ledger_before = load_ledger(paths)

    with pytest.raises(ValueError):
        await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert load_ledger(paths) == ledger_before
    assert core._publish.published == []
    assert core._report_sink.writes == []


async def test_look_conditioning_raise_is_conditioning_unreadable(tmp_path):
    core, paths = make_core(tmp_path, conditioning_inputs=FirstTwoConditioning())
    await core.capture_reference("birth")
    ledger_before = load_ledger(paths)

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditioning_unreadable"
    assert outcome.report["inconclusive_reason"] == "conditioning_unreadable"
    assert load_ledger(paths) == ledger_before
    assert core._publish.published == []


async def test_capture_conditioning_raise_is_conditioning_unreadable(tmp_path):
    core, paths = make_core(tmp_path, conditioning_inputs=RaisingConditioning())
    doc, reason = await core.capture_reference("capture")

    assert doc is None
    assert reason == "conditioning_unreadable"
    assert not paths.reference.exists()
    assert load_ledger(paths) is None


async def test_sampler_raise_is_request_failed(tmp_path):
    async def boom_sampler(_prompt: str, _seed: int) -> ProbeSample | ProbeFailure:
        raise RuntimeError("sampler boom")

    core, paths = make_core(tmp_path, conditioning_inputs=changing())
    await core.capture_reference("capture")
    ledger_before = load_ledger(paths)

    core._sampler = boom_sampler
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "request_failed"
    assert load_ledger(paths) == ledger_before

    core2, paths2 = make_core(tmp_path / "second", sampler=boom_sampler)
    doc, reason = await core2.capture_reference("capture")
    assert doc is None
    assert reason == "request_failed"
    assert not paths2.reference.exists()


async def test_unknown_reason_becomes_unclassified_failure(tmp_path):
    async def madeup_sampler(_prompt: str, _seed: int) -> ProbeSample | ProbeFailure:
        return ProbeFailure("made_up")

    core, paths = make_core(tmp_path, conditioning_inputs=changing())
    await core.capture_reference("capture")
    core._sampler = madeup_sampler

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "unclassified_failure"

    core2, _paths2 = make_core(tmp_path / "second", abort_reason=lambda: "made_up")
    doc, reason = await core2.capture_reference("capture")
    assert doc is None
    assert reason == "unclassified_failure"


async def test_statistics_failure_is_statistics_failed(tmp_path, monkeypatch):
    def raising_permutation_test(*_args, **_kwargs):
        raise ValueError("statistics boom")

    monkeypatch.setattr(
        "kaine.cycle.individuation_producer.permutation_test", raising_permutation_test
    )

    core, paths = make_core(tmp_path, conditioning_inputs=changing())
    await core.capture_reference("capture")
    core._sampler.variant = "drifted"
    ledger_before = load_ledger(paths)

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "statistics_failed"
    assert load_ledger(paths) == ledger_before
    assert core._publish.published == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_current": 1},
        {"alpha_total": 0.0},
        {"alpha_total": 1.0},
        {"effect_min": float("nan")},
    ],
)
def test_producer_settings_validation(kwargs):
    from kaine.cycle.individuation_producer import ProducerSettings

    with pytest.raises(ValueError):
        ProducerSettings(**kwargs)


async def test_ledger_reference_mismatch_is_inconclusive(tmp_path):
    core, paths = make_core(tmp_path, conditioning_inputs=changing())
    doc, _ = await core.capture_reference("capture")
    ledger = load_ledger(paths)
    tampered = dataclasses.replace(ledger, reference_id="other")
    save_ledger(paths, tampered)

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "ledger_reference_mismatch"
    assert load_ledger(paths).looks_completed == 0


async def test_incomplete_capture_can_be_replaced(tmp_path):
    core, paths = make_core(tmp_path)
    doc1, _ = await core.capture_reference("birth")
    old_id = doc1.reference_id

    paths.ledger.unlink(missing_ok=True)

    doc2, _ = await core.capture_reference("birth")
    assert doc2.reference_id != old_id
    assert paths.reference.exists()

    ledger = load_ledger(paths)
    assert ledger is not None
    assert ledger.reference_id == doc2.reference_id


async def test_capture_refused_when_reference_and_ledger_exist(tmp_path):
    core, paths = make_core(tmp_path)
    await core.capture_reference("capture")
    sampler = core._sampler
    calls = sampler.calls

    with pytest.raises(IndividuationStoreError):
        await core.capture_reference("capture")

    assert sampler.calls == calls


async def test_birth_adapter_not_copied_if_save_reference_fails(
    tmp_path, monkeypatch
):
    core, paths = make_core(tmp_path)
    source = tmp_path / "source_adapter.txt"
    source.write_text("adapter content")
    core._birth_adapter_file = lambda: source

    def raising_save(*_args, **_kwargs):
        raise OSError("save failed")

    monkeypatch.setattr(
        "kaine.cycle.individuation_producer.save_reference", raising_save
    )

    with pytest.raises(OSError):
        await core.capture_reference("birth")

    assert not paths.birth_adapter.exists()


async def test_changed_battery_is_inconclusive(tmp_path):
    core, paths = make_core(tmp_path, conditioning_inputs=changing())
    await core.capture_reference("birth")
    ledger_before = load_ledger(paths)

    core._battery = core._battery + ("A new prompt?",)
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)
    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "battery_changed"
    assert load_ledger(paths) == ledger_before
    assert core._publish.published == []
