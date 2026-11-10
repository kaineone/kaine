# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The organ window stops only the language-organ service, never the decision server."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import pytest

from kaine.decision.client import DecisionClient, DecisionConfig
from kaine.decision.schema import QUESTIONS, SCHEMA_VERSION, schema_digest
from kaine.modules.sleep.organ_window import OrganServerController, run_with_organ_window
from kaine.modules.sleep.voice_alignment import TrainingResult

MODEL_FILE = "k1-jev.gguf"
ORGAN_CONFIG = {"alias": "organ", "port": 11435}


def _single_gpu() -> dict:
    return {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]}


def _noul_id() -> str:
    for q in QUESTIONS:
        if getattr(q, "type", None) == "noul":
            return getattr(q, "key", None) or q.id
    raise RuntimeError("no noul question in schema")


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    monkeypatch.delenv("KAINE_DECISION_SERVER_API_KEY", raising=False)


@pytest.fixture
def decision_server():
    qid = _noul_id()
    answer = json.dumps(
        {"model": "k1-jev-test", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/props":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"model_path": f"/models/{MODEL_FILE}"}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", requests, thread, qid
    srv.shutdown()
    srv.server_close()


@pytest.mark.asyncio
async def test_window_stops_only_organ_and_decision_client_keeps_answering(
    decision_server, tmp_path
):
    url, requests, thread, qid = decision_server
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "schema_digest": schema_digest(),
                "thresholds": {},
                "model_file": MODEL_FILE,
            }
        )
    )
    client = DecisionClient(
        DecisionConfig(
            enabled=True, url=url, model="k1-jev-test", thresholds_path=str(sidecar)
        )
    )
    stopped: list[Any] = []
    started: list[Any] = []
    during_stop: list[Any] = []

    def stop_fn(config):
        stopped.append(config)
        during_stop.append(client.ask("during stop", None, [qid]))
        return 0

    def start_fn(config, *, adapter_path: Optional[Path]):
        started.append(config)
        return 0

    ctrl = OrganServerController(
        config=ORGAN_CONFIG, stop_fn=stop_fn, start_fn=start_fn, probe_fn=lambda: True
    )
    during_training: list[Any] = []

    async def train():
        during_training.append(client.ask("during training", None, [qid]))
        return TrainingResult(
            accepted=False, adapter_path=None, capability_loss=0.0, reason="r", samples_used=1
        )

    _result, window = await run_with_organ_window(
        train=train,
        config=ORGAN_CONFIG,
        serve_device="cuda:0",
        hot_swap_mode="restart_service",
        controller=ctrl,
        host_describer=_single_gpu,
        state_path=tmp_path / "organ_window.json",
    )

    assert window.bracketed is True
    assert stopped == [ORGAN_CONFIG]
    assert started == [ORGAN_CONFIG]
    assert len(during_stop) == 1 and during_stop[0] is not None
    assert len(during_training) == 1 and during_training[0] is not None
    assert client.ask("after window", None, [qid]) is not None
    assert thread.is_alive()
    assert "/v1/systemone" in requests
    client.close()


def test_organ_controller_never_targets_decision_server_port(monkeypatch):
    from kaine.organ_server import lifecycle

    seen: list[dict] = []
    monkeypatch.setattr(lifecycle, "cmd_stop", lambda cfg, out=None: seen.append(cfg) or 0)

    ctrl = OrganServerController(config=ORGAN_CONFIG)
    assert ctrl.unload() is True
    assert seen == [ORGAN_CONFIG]
    assert "11436" not in json.dumps(seen)
