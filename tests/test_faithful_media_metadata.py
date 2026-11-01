# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The playlist media file name never reaches the organ or its logs.

``vision.report`` and ``audition.perception`` carry ``item``, the basename of
the playlist media file. In either awareness rendering, the file name must not
appear in the organ's prompt, its notes, the published or logged
``faithful_rendering``, the intent log's ``numeric_rendering`` or the
voice-alignment training pairs. One list (``kaine.faithful.media_metadata``)
serves the renderers and the episodic store.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful import FaithfulRenderer
from kaine.faithful.felt import felt_renderer
from kaine.faithful.templates import TEMPLATES, fallback_template
from kaine.modules.language import (
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.modules.language.context import ContextAssembler, layout_digest
from kaine.modules.sleep.voice_alignment import DPOPairBuilder
from kaine.workspace.action_selection import THINK

FILM = "Some-Film-Title-1987.mkv"
MARK = "Some-Film"

VISION = {
    "change_score": 0.0004,
    "habituation_score": 0.6116,
    "encoder_model_id": "dinov2-small",
    "normalised_error": 1.2,
    "item": FILM,
    "item_order": 2,
}
AUDITION = {
    "source_label": "playlist",
    "change_score": 0.31,
    "prediction_error": 0.052,
    "energy_dbfs": -23.5,
    "normalised_error": 1.4,
    "encoder_model_id": "dasheng-base",
    "item": FILM,
    "item_order": 2,
}


def _ev(source, type_, payload, sal=0.5):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=sal,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


def _snap() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            ("v", _ev("vision", "vision.report", VISION)),
            ("a", _ev("audition", "audition.perception", AUDITION)),
        ],
        salience_scores={"v": 0.6, "a": 0.5},
    )


# --- the renderers -------------------------------------------------------------


def test_audition_perception_numeric_template():
    assert ("audition", "audition.perception") in TEMPLATES
    line = FaithfulRenderer().render_event(_ev("audition", "audition.perception", AUDITION))
    assert line == "Audition via dasheng-base reports change 0.31, prediction error 0.052."


def test_audition_perception_template_with_no_error():
    payload = {"change_score": 0.2, "prediction_error": None}
    line = FaithfulRenderer().render_event(_ev("audition", "audition.perception", payload))
    assert line == "Audition via unknown encoder reports change 0.2, prediction error none."


@pytest.mark.parametrize(
    "payload",
    [
        {"item": FILM, "x": 1},
        {"x": 1, "nested": {"item": FILM, "y": 2}},
        {"x": 1, "rows": [{"item": FILM}, {"z": 3}]},
    ],
    ids=["top", "nested", "list"],
)
def test_fallback_template_never_writes_media_metadata(payload):
    line = fallback_template("mystery", "mystery.report", payload)
    assert MARK not in line
    assert "x=1" in line


def test_fallback_with_only_media_metadata_says_no_payload():
    assert fallback_template("mystery", "mystery.report", {"item": FILM}) == (
        "mystery emitted mystery.report with no payload."
    )


def test_renderer_hands_no_template_the_media_file_name():
    seen = []

    def _peek(payload):
        seen.append(dict(payload))
        return str(payload)

    renderer = FaithfulRenderer(templates={("vision", "vision.report"): _peek})
    line = renderer.render_event(_ev("vision", "vision.report", VISION))
    assert MARK not in line
    assert "item" not in seen[0]
    assert seen[0]["item_order"] == 2


@pytest.mark.parametrize("make", [FaithfulRenderer, felt_renderer], ids=["numeric", "felt"])
@pytest.mark.parametrize("type_", ["vision.report", "audition.perception"])
def test_each_renderer_keeps_the_file_name_out(make, type_):
    source = type_.split(".")[0]
    payload = VISION if source == "vision" else AUDITION
    assert MARK not in make().render_event(_ev(source, type_, payload))


# --- the assembled context, both renderings -------------------------------------


@pytest.mark.parametrize("rendering", ["felt", "numeric"])
@pytest.mark.parametrize("mode", ["internal", "external"])
def test_assembled_context_holds_no_file_name(rendering, mode):
    ctx = ContextAssembler(awareness_rendering=rendering).assemble(
        about="Something in what I hear stands out.",
        snapshot=_snap(),
        self_model={},
        mode=mode,
        about_is_heard=False,
    )
    for field in (
        "system",
        "prompt",
        "working_memory",
        "logged_prompt",
        "logged_working_memory",
        "numeric_working_memory",
        "heard_turn",
        "logged_heard_turn",
    ):
        assert MARK not in (getattr(ctx, field) or ""), field
    # The perceptual content is still there.
    if rendering == "numeric":
        assert "Audition via dasheng-base reports change 0.31" in ctx.prompt
    else:
        assert "Audition via dasheng-base reports change 0.31" in ctx.numeric_working_memory
        assert "What I hear" in ctx.prompt


def test_layout_digest_is_unchanged():
    assert layout_digest() == "76f99c859fe8b7bb"


# --- end to end: the language module, its intent log and the pair builder -------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rendering", ["felt", "numeric"])
async def test_language_intent_log_and_training_pairs_hold_no_file_name(
    tmp_path: Path, bus: AsyncBus, rendering: str
):
    log_path = tmp_path / "intent.jsonl"
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["reply"]),
        intent_log=IntentExpressionLog(log_path),
        model_id="fake-model",
        awareness_rendering=rendering,
    )
    await language.initialize()
    try:
        language._latest_snapshot = _snap()
        await language._dispatch_intent(
            _ev(
                "action_selection",
                "intent.think",
                {
                    "kind": THINK,
                    "about": "Something in what I hear stands out noticeably.",
                    "about_kind": "felt",
                    "entry_id": "a",
                },
            )
        )
        deadline = time.monotonic() + 2.0
        entries = []
        while time.monotonic() < deadline:
            entries = await bus.client.xrange(INTERNAL_STREAM)
            if entries:
                break
            await asyncio.sleep(0.02)
        assert entries

        request = language.chat_client.requests[-1]
        assert MARK not in request.prompt
        assert MARK not in (request.system or "")

        raw = log_path.read_text()
        assert raw.strip()
        assert MARK not in raw
        record = json.loads(raw.strip().splitlines()[-1])
        assert record["faithful_rendering"]
        if rendering == "felt":
            assert "Audition via dasheng-base" in record["numeric_rendering"]

        for key in await bus.client.keys("*"):
            try:
                stream = await bus.client.xrange(key)
            except Exception:
                continue
            assert MARK not in json.dumps(stream, default=str), key

        pairs = DPOPairBuilder().build(log_path, max_pairs=10)
        assert pairs
        for pair in pairs:
            assert MARK not in pair.prompt
            assert MARK not in pair.chosen
            assert MARK not in pair.rejected
    finally:
        await language.shutdown()


@pytest.mark.parametrize("felt", [False, True], ids=["numeric", "felt"])
def test_heard_redaction_hands_no_template_the_media_file_name(felt):
    from kaine.faithful.felt import redact_heard_speech_felt
    from kaine.faithful.templates import redact_heard_speech

    event = _ev("vision", "vision.report", {**VISION, "heard_text": "hello there"})
    fn = redact_heard_speech_felt if felt else redact_heard_speech
    line = fn(event)
    assert line is not None
    assert MARK not in line
    assert "hello there" not in line
    chat = _ev("embodiment", "embodiment.chat", {"message": "hi", "item": FILM})
    assert MARK not in (fn(chat) or "")
