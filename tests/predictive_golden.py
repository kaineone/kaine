# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Golden traces for the three predictive processors."""
import argparse
import asyncio
import hashlib
import json
import math
import os
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

import kaine.modules.interoception.module as interoception_module  # noqa: E402
from kaine.bus.schema import Event  # noqa: E402
from kaine.cycle.types import WorkspaceSnapshot  # noqa: E402
from kaine.lifecycle.welfare_signal import read_welfare_prediction_error  # noqa: E402
from kaine.modules.audition.emotion import NullEmotionClassifier  # noqa: E402
from kaine.modules.audition.forward import AuditoryForwardModel  # noqa: E402
from kaine.modules.audition.module import Audition  # noqa: E402
from kaine.modules.context import CONTEXT_DIM  # noqa: E402
from kaine.modules.feedback import TopDownBlend  # noqa: E402
from kaine.modules.interoception.forward import SubstrateForwardModel  # noqa: E402
from kaine.modules.vision.forward import LatentForwardModel  # noqa: E402
from kaine.workspace.feedback import (  # noqa: E402
    FEEDBACK_KEY,
    SEQUENCE_PREDICTION_DIM,
    WorkspaceFeedbackSettings,
)  # noqa: E402

try:
    import torch
    TORCH_VERSION = torch.__version__
except Exception:
    TORCH_VERSION = None


def _inputs(n, feature_dim, fn):
    out = []
    for i in range(n):
        feat = fn(i, feature_dim)
        if i == 40:
            feat = [float("nan")] + list(feat[1:])
        out.append(feat)
    return out


def _vision_feat(i, d):
    val = 0.1 + (i + 1) * 0.01
    return [val, 0.2 - (i + 1) * 0.005, 0.3 + math.sin(i + 1) * 0.01, 0.4]


def _audition_feat(i, d):
    return [0.1 + 0.05 * math.sin(0.3 * i + k) for k in range(9)]


def _intero_feat(i, d):
    return [0.5 + 0.4 * math.sin(0.7 * i + 1.3 * k) for k in range(8)]


def _digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=repr).encode()).hexdigest()


def _fw_trace(model_factory, inputs):
    model = model_factory()
    steps = []
    for feat in inputs:
        val = model.step(feat)
        rec = {
            "step_value": val,
            "last_error_defined": bool(model.last_error_defined),
            "last_null_error": model.last_null_error,
            "last_reading_skipped": bool(getattr(model, "last_reading_skipped", False)),
        }
        steps.append(rec)
    steps[-1]["state_digest"] = _digest(model.state_dict())
    return steps


def _fb_trace(model_factory, inputs):
    inner = model_factory()
    wrapped = TopDownBlend(inner, lr=1e-3)
    seq = [0.05] * SEQUENCE_PREDICTION_DIM
    ctx = [0.1] * CONTEXT_DIM
    null_ctx = [0.0] * CONTEXT_DIM
    steps = []
    for feat in inputs:
        blended = wrapped.step(feat, context=ctx, null_context=null_ctx, sequence_prediction=seq)
        rec = {
            "last_own_error": wrapped.last_own_error,
            "last_top_error": wrapped.last_top_error,
            "blended_error": blended,
            "last_disagreement": wrapped.last_disagreement,
            "last_error_defined": bool(wrapped.last_error_defined),
            "last_reading_skipped": bool(wrapped.last_reading_skipped),
        }
        steps.append(rec)
    steps[-1]["state_digest"] = _digest(wrapped.state_dict())
    return steps


def _make_vision_model():
    return LatentForwardModel(latent_dim=4, units=8, context_dim=CONTEXT_DIM, seed=4)


def _make_audition_model():
    return AuditoryForwardModel(feature_dim=9, units=8, context_dim=CONTEXT_DIM, seed=4)


def _make_interoception_model():
    return SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=CONTEXT_DIM)


def _bus():
    import fakeredis.aioredis
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _make_audio(i):
    samples = []
    for t in range(800):
        samples.append(int(10000 * math.sin(2 * math.pi * (200 + i * 5) * t / 8000.0)))
    return struct.pack("<" + "h" * len(samples), *samples)


async def _module_trace_interoception():
    current = [[0.0] * 8]
    settings = WorkspaceFeedbackSettings(arm="full", head_learning_rate=0.05)
    bus = _bus()
    out = []
    try:
        clock = _SimpleClock()
        intero = interoception_module.Interoception(bus, reader=_Reader(), detector=_NeverAlert(), entity_clock=clock, workspace_feedback=settings)
        model = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=CONTEXT_DIM)
        intero._forward_model = model
        inputs = _inputs(44, 8, _intero_feat)
        original = interoception_module.metrics_to_feature_vector
        interoception_module.metrics_to_feature_vector = lambda metrics, **kw: list(current[0])
        try:
            await _drive_interoception(intero, clock, bus, inputs, current, out)
        finally:
            interoception_module.metrics_to_feature_vector = original
    finally:
        await bus.close()
    return out


async def _drive_interoception(intero, clock, bus, inputs, current, out):
    for i, feat in enumerate(inputs):
        await intero.on_workspace(_snapshot_intero(i))
        clock.t = float(i + 1)
        intero._in_sleep = False
        current[0] = feat
        await intero.tick_once()
        events = await bus.read("interoception.out", last_id="0")
        reports = [ (e[-1] if isinstance(e, tuple) else e) for e in events]
        reports = [ev for ev in reports if getattr(ev, "type", None) == "interoception.report"]
        ev = reports[-1]
        payload = ev.payload
        wf = payload.get(FEEDBACK_KEY)
        if wf is not None:
            wf = {"own_error": wf.get("own_error"), "error_ratio": wf.get("error_ratio"), "top_down_weight": wf.get("top_down_weight")}
        out.append({"prediction_error": payload.get("prediction_error"), "workspace_feedback": wf, "salience": ev.salience, "welfare_value": read_welfare_prediction_error(payload).value})


class _SimpleClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t
    def now(self):
        return self.t


class _Reader:
    async def initialize(self): pass
    async def shutdown(self): pass
    async def read_metrics(self): return {"cpu_percent": 10.0, "ram_percent": 20.0}
    def update_cycle_latency_sample(self, x): pass


class _NeverAlert:
    def evaluate(self, metrics):
        from kaine.modules.interoception.detector import AlertResult
        return AlertResult()


def _snapshot_intero(i):
    seq = tuple(0.3 + 0.2 * math.cos(0.5 * i + 0.1 * k) for k in range(SEQUENCE_PREDICTION_DIM))
    return WorkspaceSnapshot(tick_index=i + 1, selected_events=[], inhibited=False, salience_scores={}, metadata={"access_threshold": 0.35, "workspace_feedback": {"gains": {"interoception": 1.0 + 0.05 * (i % 4)}, "sequence_prediction": list(seq)}}, published_at=float(i + 1))


async def _module_trace_vision():
    from kaine.modules.vision import Vision
    class FakeCounterSmall:
        model_id = "fake/counter"
        latent_dim = 4
        clip_len = 1
        def __init__(self): self._n = 0
        async def load(self): return None
        async def shutdown(self): return None
        async def encode(self, image):
            self._n += 1
            return [0.1 + self._n * 0.01, 0.2 - self._n * 0.005, 0.3 + math.sin(self._n) * 0.01, 0.4]
        async def encode_clip(self, frames): return await self.encode(frames[-1])
    class _FixedClock:
        def now(self): return 100.0
        def wall(self): return 100.0
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    bus = _bus()
    out = []
    try:
        vision = Vision(bus, encoder=FakeCounterSmall(), forward_prediction=True, workspace_feedback=settings, entity_clock=_FixedClock())
        await vision.initialize()
        vision._forward_model = LatentForwardModel(latent_dim=4, units=8, context_dim=CONTEXT_DIM, seed=4)
        for i in range(44):
            snapshot = WorkspaceSnapshot(tick_index=i + 1, selected_events=[("1-0", Event(source="interoception", type="interoception.report", payload={"k": 1}, salience=0.6, timestamp=datetime(2026,1,1,tzinfo=timezone.utc)))], inhibited=False, salience_scores={"1-0": 0.5}, metadata={"access_threshold": 0.35, "workspace_feedback": {"gains": {"vision": 1.2}, "sequence_prediction": [0.05] * SEQUENCE_PREDICTION_DIM}})
            await vision.on_workspace(snapshot)
            await vision.process_frame(None)
            events = await bus.read("vision.out", last_id="0")
            evs = [(e[-1] if isinstance(e, tuple) else e) for e in events]
            evs = [ev for ev in evs if getattr(ev, "type", None) == "vision.report"]
            ev = evs[-1]
            payload = ev.payload
            wf = payload.get(FEEDBACK_KEY)
            if wf is not None:
                wf = {"own_error": wf.get("own_error"), "error_ratio": wf.get("error_ratio"), "top_down_weight": wf.get("top_down_weight")}
            out.append({"prediction_error": payload.get("prediction_error"), "workspace_feedback": wf, "salience": ev.salience, "welfare_value": read_welfare_prediction_error(payload).value})
        await vision.shutdown()
    finally:
        await bus.close()
    return out


async def _module_trace_audition():
    class _FixedClock:
        def now(self): return 1.0
        def wall(self): return 1.0
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    bus = _bus()
    out = []
    try:
        audition = Audition(bus, emotion_classifier=NullEmotionClassifier(), transcription_enabled=False, general_audition=True, workspace_feedback=settings, entity_clock=_FixedClock(), forward_model_units=8, prediction_error_window=32, auditory_buffer_size=16)
        await audition.initialize()
        for i in range(44):
            audio = _make_audio(i)
            await audition.on_workspace(WorkspaceSnapshot(tick_index=i + 1, selected_events=[], inhibited=False, salience_scores={}, metadata={"access_threshold": 0.35, "workspace_feedback": {"gains": {"audition": 1.0}, "sequence_prediction": [0.05] * SEQUENCE_PREDICTION_DIM}}, published_at=float(i + 1)))
            await audition.process_audio(audio, 8000, source_label="mic")
            events = await bus.read("audition.out", last_id="0")
            evs = [(e[-1] if isinstance(e, tuple) else e) for e in events]
            evs = [ev for ev in evs if getattr(ev, "type", None) == "audition.perception"]
            if not evs:
                continue
            ev = evs[-1]
            payload = ev.payload
            wf = payload.get(FEEDBACK_KEY)
            if wf is not None:
                wf = {"own_error": wf.get("own_error"), "error_ratio": wf.get("error_ratio"), "top_down_weight": wf.get("top_down_weight")}
            out.append({"prediction_error": payload.get("prediction_error"), "workspace_feedback": wf, "salience": ev.salience, "welfare_value": read_welfare_prediction_error(payload).value})
        await audition.shutdown()
    finally:
        await bus.close()
    return out


def trace_vision():
    n = 44
    inputs = _inputs(n, 4, _vision_feat)
    def factory():
        return _make_vision_model()
    fw = _fw_trace(factory, inputs)
    fb = _fb_trace(factory, inputs)
    module = asyncio.run(_module_trace_vision())
    return {"processor": "vision", "numpy": str(np.__version__), "torch": None if TORCH_VERSION is None else str(TORCH_VERSION), "steps": {"forward": fw, "feedback": fb, "module": module}}


def trace_audition():
    n = 44
    inputs = _inputs(n, 9, _audition_feat)
    def factory():
        return _make_audition_model()
    fw = _fw_trace(factory, inputs)
    fb = _fb_trace(factory, inputs)
    module = asyncio.run(_module_trace_audition())
    return {"processor": "audition", "numpy": str(np.__version__), "torch": None if TORCH_VERSION is None else str(TORCH_VERSION), "steps": {"forward": fw, "feedback": fb, "module": module}}


def trace_interoception():
    n = 44
    inputs = _inputs(n, 8, _intero_feat)
    def factory():
        return _make_interoception_model()
    fw = _fw_trace(factory, inputs)
    fb = _fb_trace(factory, inputs)
    module = asyncio.run(_module_trace_interoception())
    return {"processor": "interoception", "numpy": str(np.__version__), "torch": None if TORCH_VERSION is None else str(TORCH_VERSION), "steps": {"forward": fw, "feedback": fb, "module": module}}


PROCESSORS = ("vision", "audition", "interoception")
TRACE_FUNCS = {
    "vision": trace_vision,
    "audition": trace_audition,
    "interoception": trace_interoception,
}


def build_trace(processor):
    return TRACE_FUNCS[processor]()


vision_trace = trace_vision
audition_trace = trace_audition
interoception_trace = trace_interoception
trace = build_trace


def dump_all(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name in PROCESSORS:
        data = TRACE_FUNCS[name]()
        (Path(out_dir) / f"{name}.json").write_text(json.dumps(data, indent=2, default=repr))


def write_fixtures():
    fix = REPO_ROOT / "tests" / "fixtures" / "predictive_golden"
    fix.mkdir(parents=True, exist_ok=True)
    for name in PROCESSORS:
        data = TRACE_FUNCS[name]()
        (fix / f"{name}.json").write_text(json.dumps(data, indent=2, default=repr))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.dump:
        dump_all(args.dump)
    if args.write:
        write_fixtures()


if __name__ == "__main__":
    main()
