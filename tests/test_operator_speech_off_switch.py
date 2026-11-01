# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""operator-speech-as-perception, the off switch: speech-to-text off is identical to absent.

``first_configuration_trajectory`` runs the first configuration's action layer
(built by the cycle's own ``_phase_action_selection``) through a deterministic
cognitive cycle over a fixed scripted feed on a fake bus, then runs the sleep
module's ignition audit over what the cycle published. It returns every bus
entry (cycle latency aside), every broadcast, every intent, the audit record,
the audit cursors and the sleep module's serialized state, normalized for
wall-clock ids and timestamps.

The golden file ``tests/fixtures/operator_speech_off_switch.json`` was written
by this same function run against the tree without this change (the base of
the change), so the test compares "with this change" to "without it" on the
same seeded feed.
"""
from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "fixtures" / "operator_speech_off_switch.json"
BASE_TS = "2026-01-01T00:00:00+00:00"


def _fields(source: str, type_: str, payload: dict, salience: float) -> dict:
    return {
        "source": source,
        "type": type_,
        "salience": repr(float(salience)),
        "timestamp": BASE_TS,
        "causal_parent": "",
        "payload": json.dumps(payload, sort_keys=True),
    }


def _feed(k: int) -> list[tuple[str, str, str, dict, float]]:
    """Tick ``k``'s new entries: (stream, source, type, payload, intensity)."""
    out = [
        ("audition.out", "audition", "audition.perception", {"source_label": "playlist", "change": 0.1 * (k % 5), "prediction_error": 0.2 + 0.05 * (k % 7)}, 0.3 + 0.07 * (k % 6)),
        ("audition.out", "audition", "audition.prosody", {"source_label": "playlist", "pitch_hz": 120.0 + k}, 0.2),
        ("vision.out", "vision", "vision.percept", {"change": 0.05 * (k % 9)}, 0.25 + 0.09 * (k % 8)),
        ("interoception.out", "interoception", "interoception.report", {"wellness": 0.5 + 0.01 * k}, 0.3),
        ("sequence.out", "sequence", "sequence.error", {"error": 0.1 * (k % 4)}, 0.2 + 0.1 * (k % 4)),
    ]
    if k % 4 == 0:
        out.append(("affect.out", "affect", "affect.drive", {"drive": "curiosity", "value": 0.8}, 0.6 + 0.05 * (k % 3)))
    if k % 6 == 3:
        out.append(("affect.out", "affect", "affect.drive", {"drive": "social_drive", "value": 0.9}, 0.75))
    return out


def _load_first_configuration(tmp_path: Path) -> dict[str, Any]:
    from kaine.config import load_kaine_config

    operator = tmp_path / "empty.operator.toml"
    operator.write_text("", encoding="utf-8")
    return load_kaine_config(
        REPO / "config" / "kaine.toml",
        operator,
        profile="first_configuration",
        profiles_dir=REPO / "config" / "profiles",
    )


def _norm_stream(entries: list) -> list:
    out = []
    for _entry_id, fields in entries:
        rec = {k: v for k, v in fields.items() if k != "timestamp"}
        for key in ("payload", "snapshot"):
            if key in rec:
                rec[key] = json.loads(rec[key])
        out.append(rec)
    return out


async def first_configuration_trajectory(tmp_path: Path, ticks: int = 24) -> dict[str, Any]:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.cycle import __main__ as cm
    from kaine.cycle.boot_context import BootContext
    from kaine.cycle.engine import CognitiveCycle
    from kaine.experiment import set_global_seed
    from kaine.modules.sleep.module import Sleep
    from kaine.modules.sleep.voice_alignment import VoiceAlignmentConfig
    from kaine.workspace import (
        NoveltyTracker,
        RuleBasedSalience,
        StaticAffectModulator,
        StaticGoalScorer,
        Workspace,
    )
    from tests._fakes import FakeClock, FakeRegistry

    cfg = _load_first_configuration(tmp_path)
    assert (cfg.get("audition") or {}).get("transcription_enabled") is False
    set_global_seed(0)
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        clock = FakeClock()
        ctx = BootContext()
        ctx.kaine_config = cfg
        ctx.registry = types.SimpleNamespace(entity_clock=types.SimpleNamespace(now=clock, wall=clock))
        ctx.run_ctx = types.SimpleNamespace(run_id="off-switch", seed=0)
        ctx.intent_secret = b"0" * 32
        assert await cm._phase_action_selection(ctx) is None

        streams = sorted({s for k in range(ticks) for s, *_ in _feed(k)})
        cycle = CognitiveCycle(
            bus=bus,
            workspace=Workspace(
                strategy=RuleBasedSalience(
                    novelty=NoveltyTracker(window=32),
                    goal_scorer=StaticGoalScorer(),
                    affect_modulator=StaticAffectModulator(),
                ),
                top_k=5,
                publication_threshold=0.35,
            ),
            registry=FakeRegistry(streams),
            action_selection=ctx.action_selection,
            clock=clock,
            sleep=clock.sleep,
            deterministic=True,
        )
        for k in range(ticks):
            for j, (stream, source, type_, payload, salience) in enumerate(_feed(k)):
                await client.xadd(stream, _fields(source, type_, payload, salience), id=f"{1000 + k}-{j}")
            await cycle.tick()
            clock.advance(2.0)
        # Two utterances realized, as the language module would publish them.
        for i in range(2):
            await client.xadd(
                "language.external",
                _fields("language", "external_speech", {"mode": "external", "record_id": f"R{i}"}, 0.4),
                id=f"{2000 + i}-0",
            )

        from kaine.entity_clock import EntityClock

        sleep = Sleep(
            bus,
            entity_clock=EntityClock(monotonic=clock, real_sleep=clock.sleep),
            voice_alignment_config=VoiceAlignmentConfig(
                intent_log_path=tmp_path / "language" / "intent_expression.jsonl",
                adapter_output_dir=tmp_path / "adapters",
            ),
        )
        cursor_keys_before = sorted(sleep._audit_cursors)
        audit = await sleep._run_ignition_audit()

        bus_entries: dict[str, Any] = {}
        for key in sorted(await client.keys("*")):
            if key == "cycle.out":
                continue  # wall-clock latency, not experience
            if await client.type(key) != "stream":
                continue
            bus_entries[key] = _norm_stream(await client.xrange(key))
        ids_by_stream = {k: [e for e, _ in await client.xrange(k)] for k in await client.keys("*") if await client.type(k) == "stream"}

        def _cursor_index(stream: str, cursor: str) -> Any:
            ids = ids_by_stream.get(stream, [])
            return ids.index(cursor) if cursor in ids else cursor

        return {
            "bus": bus_entries,
            "audit": audit,
            "audit_cursor_keys_before": cursor_keys_before,
            "audit_cursors_after": {s: _cursor_index(s, c) for s, c in sorted(sleep._audit_cursors.items())},
            "broadcast_cursor_after": _cursor_index("workspace.broadcast", sleep._broadcast_cursor),
            "sleep_state": sleep.serialize(),
        }
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_first_configuration_off_switch_identical_to_without_the_change(tmp_path):
    """Speech-to-text off (the first configuration): every bus entry, broadcast,
    intent, the audit record, its cursors and the sleep state are identical to
    the base tree's on the same seeded feed."""
    current = json.loads(json.dumps(await first_configuration_trajectory(tmp_path), sort_keys=True, default=str))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    # The run is not vacuous: broadcasts and intents of both kinds happened.
    kinds = {e["payload"]["kind"] for e in current["bus"]["action_selection.out"]}
    assert {"speak", "think"} <= kinds
    assert current["bus"]["workspace.broadcast"]
    assert "sleep_readout.out" not in current["bus"]
    assert current == golden


def _write_golden(path: Path, tmp: Path) -> None:  # pragma: no cover - run by hand on the base tree
    data = asyncio.run(first_configuration_trajectory(tmp))
    path.write_text(json.dumps(data, sort_keys=True, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        _write_golden(Path(sys.argv[1]), Path(d))
