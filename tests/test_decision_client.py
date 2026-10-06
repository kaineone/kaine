# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev decision client."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from kaine.decision.client import DecisionClient, DecisionConfig, load_thresholds
from kaine.decision.schema import (
    QUESTIONS,
    SCHEMA_VERSION,
    schema_digest,
    state_text,
    systemone_questions,
)


def _first_id(kind: str) -> str:
    """Return the first known question id of the given type."""
    for q in QUESTIONS:
        if getattr(q, "type", None) == kind:
            key = getattr(q, "key", None) or getattr(q, "id", None)
            if key:
                return key
    raise RuntimeError(f"No {kind} question in schema")


def _make_server(
    response: bytes = b"{}",
    status: int = 200,
    content_type: str = "application/json",
):
    """Start a local HTTP server that records POSTs and returns canned data."""

    class Handler(BaseHTTPRequestHandler):
        _response = response
        _status = status
        _content_type = content_type
        _requests: list[dict] = []

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.__class__._requests.append(
                {"path": self.path, "headers": dict(self.headers), "body": body}
            )
            self.send_response(self.__class__._status)
            self.send_header("Content-Type", self.__class__._content_type)
            self.end_headers()
            self.wfile.write(self.__class__._response)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}", server, Handler


@pytest.fixture
def server():
    url, srv, handler = _make_server()
    yield url, srv, handler
    srv.shutdown()
    srv.server_close()


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    monkeypatch.delenv("KAINE_DECISION_SERVER_API_KEY", raising=False)


def test_ask_disabled(server):
    url, _srv, handler = server
    client = DecisionClient(DecisionConfig(enabled=False, url=url))
    assert client.ask("hello", None, [_first_id("noul")]) is None
    assert handler._requests == []
    client.close()


def test_request_shape(server, monkeypatch):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    monkeypatch.setenv("KAINE_DECISION_SERVER_API_KEY", "")
    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, model="k1-jev-test")
    )
    result = client.ask("hello world", "ctx", [qid])
    assert result is not None

    req = handler._requests[0]
    assert req["path"] == "/v1/systemone"
    assert "Authorization" not in req["headers"]

    body = json.loads(req["body"])
    assert list(body.keys()) == ["state", "questions", "model"]
    assert body["state"] == state_text("hello world", "ctx")
    assert body["questions"] == systemone_questions([qid])
    assert body["model"] == "k1-jev-test"
    client.close()


def test_bearer_key_present(server, monkeypatch, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    monkeypatch.setenv("KAINE_DECISION_SERVER_API_KEY", "secret-key-123")
    client = DecisionClient(DecisionConfig(enabled=True, url=url))

    marker = "UNIQUE_BEARER_MARKER"
    with caplog.at_level("WARNING"):
        result = client.ask(marker, None, [qid])
    assert result is not None

    req = handler._requests[0]
    assert req["headers"].get("Authorization") == "Bearer secret-key-123"
    assert marker not in caplog.text
    assert "secret-key-123" not in caplog.text
    client.close()


def test_bearer_key_absent(server, monkeypatch):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    monkeypatch.delenv("KAINE_DECISION_SERVER_API_KEY", raising=False)
    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    result = client.ask("hello", None, [qid])
    assert result is not None
    req = handler._requests[0]
    assert "Authorization" not in req["headers"]
    client.close()


def test_noul_with_threshold(tmp_path, server):
    url, _srv, handler = server
    qid = _first_id("noul")
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "schema_digest": schema_digest(),
                "thresholds": {qid: 0.31},
            }
        )
    )

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(threshold_path))
    )

    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.31}}, "usage": {}}
    ).encode()
    ans = client.ask("x", None, [qid])[qid]
    assert ans.type == "noul"
    assert ans.noul == pytest.approx(0.31)
    assert ans.probabilities == {
        "true": pytest.approx(0.31),
        "false": pytest.approx(0.69),
    }
    assert ans.decided is True

    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.30}}, "usage": {}}
    ).encode()
    ans = client.ask("x", None, [qid])[qid]
    assert ans.decided is False
    client.close()


def test_noul_without_threshold(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.31}}, "usage": {}}
    ).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    ans = client.ask("x", None, [qid])[qid]
    assert ans.decided is None
    client.close()


def test_choice_parsing(server):
    url, _srv, handler = server
    qid = _first_id("choice")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 0.8, "no": 0.2},
                    "confidence": 0.9,
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    ans = client.ask("x", None, [qid])[qid]
    assert ans.type == "choice"
    assert ans.choice == "yes"
    assert ans.probabilities == pytest.approx({"yes": 0.8, "no": 0.2})
    assert ans.score is None
    assert ans.noul is None
    assert ans.decided is None
    client.close()


def test_score_parsing(server):
    url, _srv, handler = server
    qid = _first_id("score")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "score",
                    "score": 2.5,
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4},
                    "legend": {},
                    "confidence": 0.8,
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    ans = client.ask("x", None, [qid])[qid]
    assert ans.type == "score"
    assert ans.score == pytest.approx(2.5)
    assert ans.probabilities == pytest.approx(
        {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4}
    )
    assert ans.choice is None
    assert ans.noul is None
    assert ans.decided is None
    client.close()


def test_failure_connection_refused(server):
    url, srv, _handler = server
    srv.shutdown()
    srv.server_close()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [_first_id("noul")]) is None
    client.close()


def test_failure_500(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 500
    handler._response = b"error"

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_501(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 501
    handler._response = b"not implemented"

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_non_json(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = b"not json"
    handler._content_type = "text/plain"

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_missing_answers(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps({"model": "k1-jev", "usage": {}}).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_missing_id(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {"other-id": {"type": "noul", "noul": 0.5}},
            "usage": {},
        }
    ).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_wrong_type(server):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 1.0},
                    "confidence": 1.0,
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_nan_probability(server):
    url, _srv, handler = server
    qid = _first_id("choice")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": float("nan"), "no": 0.5},
                    "confidence": 1.0,
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(DecisionConfig(enabled=True, url=url))
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_rate_limited_logging(server, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 500
    handler._response = b"error"

    now = [0.0]
    client = DecisionClient(
        DecisionConfig(enabled=True, url=url),
        clock=lambda: now[0],
    )

    marker = "RATE_LIMIT_MARKER"
    with caplog.at_level("WARNING"):
        assert client.ask(marker, None, [qid]) is None
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

        now[0] = 30.0
        assert client.ask(marker, None, [qid]) is None
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

        now[0] = 61.0
        assert client.ask(marker, None, [qid]) is None
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 2

    assert marker not in caplog.text
    client.close()


def test_config_defaults():
    assert DecisionConfig.from_section(None) == DecisionConfig()
    assert DecisionConfig.from_section({}) == DecisionConfig()


def test_config_from_section():
    cfg = DecisionConfig.from_section(
        {
            "enabled": True,
            "url": "http://example",
            "model": "m",
            "timeout_s": 2.0,
            "thresholds_path": "/tmp/t.json",
        }
    )
    assert cfg == DecisionConfig(
        enabled=True,
        url="http://example",
        model="m",
        timeout_s=2.0,
        thresholds_path="/tmp/t.json",
    )


def test_config_unknown_key():
    with pytest.raises(ValueError, match="Unknown decision config key: 'bad_key'"):
        DecisionConfig.from_section({"bad_key": 1})


def test_load_thresholds_good(tmp_path):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "schema_digest": schema_digest(),
                "thresholds": {qid: 0.31},
            }
        )
    )
    assert load_thresholds(str(path)) == {qid: pytest.approx(0.31)}


def test_load_thresholds_wrong_digest(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "schema_digest": "not-the-digest",
                "thresholds": {qid: 0.31},
            }
        )
    )
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "digest" in caplog.text.lower()


def test_load_thresholds_wrong_version(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "schema_digest": schema_digest(),
                "thresholds": {qid: 0.31},
            }
        )
    )
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "version" in caplog.text.lower()


def test_load_thresholds_unknown_id(tmp_path, caplog):
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "schema_digest": schema_digest(),
                "thresholds": {"not_a_question": 0.5},
            }
        )
    )
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "unknown" in caplog.text.lower()


def test_load_thresholds_out_of_range(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "schema_digest": schema_digest(),
                "thresholds": {qid: 1.5},
            }
        )
    )
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "range" in caplog.text.lower()


def test_load_thresholds_missing_file(tmp_path, caplog):
    path = tmp_path / "does-not-exist.json"
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert caplog.records


def test_load_thresholds_empty_path(caplog):
    with caplog.at_level("WARNING"):
        assert load_thresholds("") is None
    assert not caplog.records


def test_import_boundary():
    root = Path(__file__).resolve().parent.parent
    script = """
import sys
import kaine.decision.client as client
forbidden = ("kaine.modules", "kaine.evaluation", "kaine.cycle", "kaine.nexus")
loaded = [name for name in forbidden if name in sys.modules]
if loaded:
    print("forbidden", loaded)
"""
    env = os.environ.copy()
    env.pop("KAINE_DECISION_SERVER_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "forbidden" not in result.stdout


def test_ask_never_raises_on_an_unexpected_error():
    # An unknown question id fails while the request is built (KeyError),
    # before any HTTP call: ask must still return None, never raise.
    cfg = DecisionConfig(enabled=True, url="http://127.0.0.1:9")
    client = DecisionClient(cfg)
    try:
        assert client.ask("hello", None, ["no_such_question"]) is None
    finally:
        client.close()
