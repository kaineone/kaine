# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev decision client."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from kaine.decision.client import (
    DecisionClient,
    DecisionConfig,
    load_sidecar,
    load_thresholds,
)
from kaine.decision.schema import (
    QUESTIONS,
    SCHEMA_VERSION,
    get_question,
    schema_digest,
    state_text,
    systemone_questions,
)

MODEL_FILE = "k1-jev.gguf"
PROPS_RESPONSE = {"model_path": f"/models/{MODEL_FILE}"}


def _first_id(kind: str) -> str:
    """Return the first known question id of the given type."""
    for q in QUESTIONS:
        if getattr(q, "type", None) == kind:
            key = getattr(q, "key", None) or getattr(q, "id", None)
            if key:
                return key
    raise RuntimeError(f"No {kind} question in schema")


def _write_sidecar(
    path: Path,
    thresholds: dict | None = None,
    model_file: str = MODEL_FILE,
    model_sha256: str | None = None,
) -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        "schema_digest": schema_digest(),
        "thresholds": thresholds or {},
        "model_file": model_file,
    }
    if model_sha256 is not None:
        data["model_sha256"] = model_sha256
    path.write_text(json.dumps(data))


@pytest.fixture
def sidecar_path(tmp_path: Path) -> Path:
    """A valid sidecar file with no thresholds."""
    path = tmp_path / "sidecar.json"
    _write_sidecar(path)
    return path


def _make_server(
    response: bytes = b"{}",
    status: int = 200,
    content_type: str = "application/json",
    props_response: dict | None = None,
):
    """Start a local HTTP server that records requests and returns canned data.

    GET /props returns *props_response* (200 by default). POST /v1/systemone
    returns *response* with *status*.
    """
    if props_response is None:
        props_response = PROPS_RESPONSE

    class Handler(BaseHTTPRequestHandler):
        _response = response
        _status = status
        _content_type = content_type
        _props_response = props_response
        _props_status = 200
        _requests: list[dict] = []

        def do_GET(self):
            self.__class__._requests.append(
                {"path": self.path, "headers": dict(self.headers), "body": b""}
            )
            if self.path == "/props" and self.__class__._props_response is not None:
                self.send_response(self.__class__._props_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(self.__class__._props_response).encode()
                )
            else:
                self.send_response(404)
                self.end_headers()

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


def _props_requests(handler) -> list[dict]:
    return [r for r in handler._requests if r["path"] == "/props"]


def _systemone_requests(handler) -> list[dict]:
    return [r for r in handler._requests if r["path"] == "/v1/systemone"]


def test_ask_disabled(server):
    url, _srv, handler = server
    client = DecisionClient(DecisionConfig(enabled=False, url=url))
    assert client.ask("hello", None, [_first_id("noul")]) is None
    assert handler._requests == []
    client.close()


def test_request_shape(server, monkeypatch, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev-test", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    monkeypatch.setenv("KAINE_DECISION_SERVER_API_KEY", "")
    client = DecisionClient(
        DecisionConfig(
            enabled=True,
            url=url,
            model="k1-jev-test",
            thresholds_path=str(sidecar_path),
        )
    )
    result = client.ask("hello world", "ctx", [qid])
    assert result is not None

    assert len(_props_requests(handler)) == 1
    props_req = _props_requests(handler)[0]
    assert props_req["path"] == "/props"
    assert "Authorization" not in props_req["headers"]

    assert len(_systemone_requests(handler)) == 1
    req = _systemone_requests(handler)[0]
    assert req["path"] == "/v1/systemone"
    assert "Authorization" not in req["headers"]

    body = json.loads(req["body"])
    assert list(body.keys()) == ["state", "questions", "model"]
    assert body["state"] == state_text("hello world", "ctx")
    assert body["questions"] == systemone_questions([qid])
    assert body["model"] == "k1-jev-test"
    client.close()


def test_bearer_key_present(server, monkeypatch, caplog, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    monkeypatch.setenv("KAINE_DECISION_SERVER_API_KEY", "secret-key-123")
    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )

    marker = "UNIQUE_BEARER_MARKER"
    with caplog.at_level("WARNING"):
        result = client.ask(marker, None, [qid])
    assert result is not None

    for req in handler._requests:
        if req["path"] in ("/props", "/v1/systemone"):
            assert req["headers"].get("Authorization") == "Bearer secret-key-123"

    assert marker not in caplog.text
    assert "secret-key-123" not in caplog.text
    client.close()


def test_bearer_key_absent(server, monkeypatch, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    monkeypatch.delenv("KAINE_DECISION_SERVER_API_KEY", raising=False)
    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    result = client.ask("hello", None, [qid])
    assert result is not None
    for req in handler._requests:
        assert "Authorization" not in req["headers"]
    client.close()


def test_noul_with_threshold(tmp_path, server):
    url, _srv, handler = server
    qid = _first_id("noul")
    sidecar = tmp_path / "thresholds.json"
    _write_sidecar(sidecar, thresholds={qid: 0.31})

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar))
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


def test_noul_without_threshold(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.31}}, "usage": {}}
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    ans = client.ask("x", None, [qid])[qid]
    assert ans.decided is None
    client.close()


def test_choice_parsing(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("choice")
    o0, o1 = [o.key for o in get_question(qid).options][:2]
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": o0,
                    "probabilities": {o0: 0.8, o1: 0.2},
                    "confidence": 0.9,
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    ans = client.ask("x", None, [qid])[qid]
    assert ans.type == "choice"
    assert ans.choice == o0
    assert ans.probabilities == pytest.approx({o0: 0.8, o1: 0.2})
    assert ans.score is None
    assert ans.noul is None
    assert ans.decided is None
    client.close()


def test_score_parsing(server, sidecar_path):
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

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
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


def test_failure_connection_refused_is_identity_unavailable(
    server, sidecar_path, caplog
):
    url, srv, _handler = server
    srv.shutdown()
    srv.server_close()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [_first_id("noul")]) is None
    assert "identity_unavailable" in caplog.text
    client.close()


def test_failure_500(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 500
    handler._response = b"error"

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_501(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 501
    handler._response = b"not implemented"

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_non_json(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = b"not json"
    handler._content_type = "text/plain"

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_missing_answers(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps({"model": "k1-jev", "usage": {}}).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_missing_id(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {"other-id": {"type": "noul", "noul": 0.5}},
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_wrong_type(server, sidecar_path):
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

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_failure_nan_probability(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("choice")
    o0, o1 = [o.key for o in get_question(qid).options][:2]
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": o0,
                    "probabilities": {o0: float("nan"), o1: 0.5},
                    "confidence": 1.0,
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is None
    client.close()


def test_rate_limited_logging(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 500
    handler._response = b"error"

    now = [0.0]
    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path)),
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
            "url": "http://127.0.0.1:11999",
            "model": "m",
            "timeout_s": 2.0,
            "thresholds_path": "/tmp/t.json",
        }
    )
    assert cfg == DecisionConfig(
        enabled=True,
        url="http://127.0.0.1:11999",
        model="m",
        timeout_s=2.0,
        thresholds_path="/tmp/t.json",
    )


def test_config_unknown_key():
    with pytest.raises(ValueError, match="Unknown decision config key: 'bad_key'"):
        DecisionConfig.from_section({"bad_key": 1})


def test_config_enabled_not_bool_in_from_section():
    with pytest.raises(ValueError, match="enabled"):
        DecisionConfig.from_section({"enabled": "false"})


def test_config_enabled_not_bool_direct():
    with pytest.raises(ValueError, match="enabled"):
        DecisionConfig(enabled="false", url="http://127.0.0.1:1")


@pytest.mark.parametrize(
    "timeout_s",
    [0, -1, float("nan"), True],
    ids=["zero", "negative", "nan", "bool"],
)
def test_config_timeout_s_invalid(timeout_s):
    with pytest.raises(ValueError, match="timeout_s"):
        DecisionConfig(enabled=True, url="http://127.0.0.1:1", timeout_s=timeout_s)


def test_load_thresholds_good(tmp_path):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    _write_sidecar(path, thresholds={qid: 0.31})
    assert load_thresholds(str(path)) == {qid: pytest.approx(0.31)}


def test_load_sidecar_good(tmp_path):
    qid = _first_id("noul")
    path = tmp_path / "sidecar.json"
    _write_sidecar(path, thresholds={qid: 0.31}, model_sha256="abc")
    sidecar = load_sidecar(str(path))
    assert sidecar is not None
    assert sidecar.thresholds == {qid: pytest.approx(0.31)}
    assert sidecar.model_file == MODEL_FILE
    assert sidecar.model_sha256 == "abc"


def test_load_thresholds_wrong_digest(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    _write_sidecar(path, thresholds={qid: 0.31})
    data = json.loads(path.read_text())
    data["schema_digest"] = "not-the-digest"
    path.write_text(json.dumps(data))
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "digest" in caplog.text.lower()


def test_load_thresholds_wrong_version(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    _write_sidecar(path, thresholds={qid: 0.31})
    data = json.loads(path.read_text())
    data["schema_version"] = 999
    path.write_text(json.dumps(data))
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "version" in caplog.text.lower()


def test_load_thresholds_unknown_id(tmp_path, caplog):
    path = tmp_path / "thresholds.json"
    _write_sidecar(path, thresholds={"not_a_question": 0.5})
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "unknown" in caplog.text.lower()


def test_load_thresholds_out_of_range(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    _write_sidecar(path, thresholds={qid: 1.5})
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


def test_load_thresholds_non_object_is_missing(tmp_path, caplog):
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps([1, 2]))
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "object" in caplog.text.lower()


def test_load_thresholds_missing_model_file(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "thresholds.json"
    _write_sidecar(path, thresholds={qid: 0.31})
    data = json.loads(path.read_text())
    del data["model_file"]
    path.write_text(json.dumps(data))
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert "model_file" in caplog.text.lower()


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


def test_ask_never_raises_on_an_unexpected_error(sidecar_path):
    # An unknown question id fails while the request is built (KeyError),
    # before any HTTP call: ask must still return None, never raise.
    cfg = DecisionConfig(
        enabled=True,
        url="http://127.0.0.1:9",
        thresholds_path=str(sidecar_path),
    )
    client = DecisionClient(cfg)
    try:
        assert client.ask("hello", None, ["no_such_question"]) is None
    finally:
        client.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:11436",
        "https://127.0.0.1:11436",
        "http://10.0.0.5:11436",
        "http://127.0.0.1.evil.example:11436",
    ],
)
def test_non_local_urls_are_refused(url):
    with pytest.raises(ValueError):
        DecisionConfig(enabled=True, url=url)
    with pytest.raises(ValueError):
        DecisionConfig.from_section({"enabled": True, "url": url})


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11436",
        "http://localhost:11436",
        "http://[::1]:11436",
        "http://kaine-decision-model:8080",
    ],
)
def test_local_urls_are_accepted(url):
    assert DecisionConfig(enabled=True, url=url).url == url


def test_a_non_local_url_never_sends_the_key_or_the_utterance(monkeypatch):
    """Even if a config with a remote URL is forced past DecisionConfig, the
    client refuses at construction: no request, so neither the key nor the
    entity's speech leaves the process."""
    sent = []
    transport = httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200, json={})
    )
    monkeypatch.setenv("KAINE_DECISION_SERVER_API_KEY", "k-secret-marker")
    cfg = DecisionConfig(enabled=True)
    object.__setattr__(cfg, "url", "http://attacker.example:80")  # bypass __post_init__
    with pytest.raises(ValueError):
        DecisionClient(cfg, transport=transport)
    assert sent == []


def test_owned_client_ignores_environment_proxies(monkeypatch, sidecar_path):
    """HTTP_PROXY / ALL_PROXY must not reroute the key or the utterance."""
    qid = _first_id("noul")
    response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()
    url, srv, handler = _make_server(response=response)
    client = None
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)

        client = DecisionClient(
            DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
        )
        result = client.ask("hello", None, [qid])
        assert result is not None
        assert result[qid].noul == pytest.approx(0.5)
        assert len(handler._requests) == 2  # GET /props + POST /systemone
    finally:
        if client is not None:
            client.close()
        srv.shutdown()
        srv.server_close()


def test_owned_client_flags():
    client = DecisionClient(DecisionConfig(enabled=True))
    assert client._client.trust_env is False
    assert client._client.follow_redirects is False
    client.close()

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    client = DecisionClient(DecisionConfig(enabled=True), transport=transport)
    assert client._client.trust_env is False
    assert client._client.follow_redirects is False
    client.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://u@127.0.0.1:1",
        "http://u:p@127.0.0.1:1",
        "http://127.0.0.1:1/?a=b",
        "http://127.0.0.1:1/#f",
    ],
)
def test_url_credentials_queries_and_fragments_are_refused(url):
    with pytest.raises(ValueError):
        DecisionConfig(enabled=True, url=url)
    with pytest.raises(ValueError):
        DecisionConfig.from_section({"enabled": True, "url": url})


def test_load_thresholds_missing_path_does_not_leak_path(tmp_path, caplog):
    path = tmp_path / "missing-secret-path.json"
    with caplog.at_level("WARNING"):
        assert load_thresholds(str(path)) is None
    assert caplog.records
    assert str(path) not in caplog.text


@pytest.mark.parametrize("noul", [1.5, -0.1])
def test_noul_out_of_bounds_is_missing(server, sidecar_path, noul):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": noul}}, "usage": {}}
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    try:
        assert client.ask("x", None, [qid]) is None
    finally:
        client.close()


def test_choice_bogus_is_missing(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("choice")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {qid: {"type": "choice", "choice": "BOGUS"}},
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "out_of_schema" in caplog.text
    client.close()


@pytest.mark.parametrize("score", [999, -1, float("nan")])
def test_score_out_of_bounds_or_nan_is_missing(server, sidecar_path, score):
    url, _srv, handler = server
    qid = _first_id("score")
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {qid: {"type": "score", "score": score}},
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    try:
        assert client.ask("x", None, [qid]) is None
    finally:
        client.close()


def test_choice_probability_unknown_key_is_missing(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("choice")
    o0, o1 = [o.key for o in get_question(qid).options][:2]
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": o0,
                    "probabilities": {o0: 0.5, "unknown": 0.5},
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "out_of_schema" in caplog.text
    client.close()


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_choice_probability_out_of_range_is_missing(
    server, sidecar_path, caplog, value
):
    url, _srv, handler = server
    qid = _first_id("choice")
    o0, o1 = [o.key for o in get_question(qid).options][:2]
    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                qid: {
                    "type": "choice",
                    "choice": o0,
                    "probabilities": {o0: value, o1: 0.0},
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "out_of_schema" in caplog.text
    client.close()


def test_answer_type_mismatch_is_missing(server, sidecar_path, caplog):
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
                }
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "out_of_schema" in caplog.text
    client.close()


@pytest.mark.parametrize(
    "response_model", ["other-model", None], ids=["different", "missing"]
)
def test_response_model_mismatch_is_missing(
    server, sidecar_path, caplog, response_model
):
    url, _srv, handler = server
    qid = _first_id("noul")
    payload = {
        "answers": {qid: {"type": "noul", "noul": 0.5}},
        "usage": {},
    }
    if response_model is not None:
        payload["model"] = response_model
    handler._response = json.dumps(payload).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, model="k1-jev", thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "model_mismatch" in caplog.text
    client.close()


def test_valid_response_still_parses_exactly_as_before(server, sidecar_path):
    url, _srv, handler = server
    noul_qid = _first_id("noul")
    choice_qid = _first_id("choice")
    o0, o1 = [o.key for o in get_question(choice_qid).options][:2]
    score_qid = _first_id("score")
    levels = len(get_question(score_qid).options)
    score_probs = {str(i): 1.0 / levels for i in range(levels)}

    handler._response = json.dumps(
        {
            "model": "k1-jev",
            "answers": {
                noul_qid: {"type": "noul", "noul": 0.42},
                choice_qid: {
                    "type": "choice",
                    "choice": o0,
                    "probabilities": {o0: 0.8, o1: 0.2},
                },
                score_qid: {
                    "type": "score",
                    "score": 1.5,
                    "probabilities": score_probs,
                },
            },
            "usage": {},
        }
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    result = client.ask("x", None, [noul_qid, choice_qid, score_qid])
    assert result is not None
    assert result[noul_qid].noul == pytest.approx(0.42)
    assert result[choice_qid].choice == o0
    assert result[choice_qid].probabilities == pytest.approx({o0: 0.8, o1: 0.2})
    assert result[score_qid].score == pytest.approx(1.5)
    assert result[score_qid].probabilities == pytest.approx(score_probs)
    client.close()


def test_identity_mismatch_returns_none(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._props_response = {"model_path": "/models/other-model.gguf"}
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "identity_mismatch" in caplog.text
    assert len(_systemone_requests(handler)) == 0
    client.close()


def test_props_non_200_returns_identity_unavailable(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._props_status = 503
    handler._props_response = {}
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "identity_unavailable" in caplog.text
    assert len(_systemone_requests(handler)) == 0
    client.close()


def test_identity_rechecked_after_failure(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._status = 500
    handler._response = b"error"

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )

    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
        assert len(_props_requests(handler)) == 1

        assert client.ask("x", None, [qid]) is None
        assert len(_props_requests(handler)) == 2

        handler._status = 200
        handler._response = json.dumps(
            {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
        ).encode()
        # The previous ask failed, so this one re-checks the identity first.
        result = client.ask("x", None, [qid])
        assert result is not None
        assert len(_props_requests(handler)) == 3

        # Verified now: the next ask does not re-check.
        assert client.ask("x", None, [qid]) is not None
        assert len(_props_requests(handler)) == 3

    client.close()


def test_identity_not_rechecked_while_verified(server, sidecar_path):
    url, _srv, handler = server
    qid = _first_id("noul")
    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 1

    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 1
    client.close()


def test_identity_rechecked_after_an_out_of_schema_answer(server, sidecar_path):
    """An answer that fails parsing also clears the verified identity, so the
    next ask re-checks /props before trusting the server again."""
    url, _srv, handler = server
    qid = _first_id("noul")
    good = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()
    handler._response = good
    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 1

    handler._response = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 1.5}}, "usage": {}}
    ).encode()
    assert client.ask("x", None, [qid]) is None  # out of schema
    assert len(_props_requests(handler)) == 1

    handler._response = good
    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 2  # re-checked after the failure
    client.close()


def test_no_sidecar_returns_none(server, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    client = DecisionClient(DecisionConfig(enabled=True, url=url))

    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "no_sidecar" in caplog.text
    assert handler._requests == []
    client.close()


def test_sidecar_without_model_file_is_refused(tmp_path, caplog):
    qid = _first_id("noul")
    path = tmp_path / "sidecar.json"
    _write_sidecar(path, thresholds={qid: 0.31})
    data = json.loads(path.read_text())
    del data["model_file"]
    path.write_text(json.dumps(data))

    with caplog.at_level("WARNING"):
        assert load_sidecar(str(path)) is None
        assert load_thresholds(str(path)) is None
    assert "model_file" in caplog.text.lower()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {
                "model": "k1-jev",
                "answers": {"QID": {"type": "noul", "noul": True}},
                "usage": {},
            },
            id="noul",
        ),
        pytest.param(
            {
                "model": "k1-jev",
                "answers": {"QID": {"type": "score", "score": True}},
                "usage": {},
            },
            id="score",
        ),
        pytest.param(
            {
                "model": "k1-jev",
                "answers": {
                    "QID": {
                        "type": "choice",
                        "choice": "OPT0",
                        "probabilities": {"OPT0": True},
                    }
                },
                "usage": {},
            },
            id="probability",
        ),
    ],
)
def test_boolean_value_is_out_of_schema(server, sidecar_path, caplog, payload):
    url, _srv, handler = server
    qid = _first_id(payload["answers"]["QID"]["type"])
    payload = json.loads(json.dumps(payload).replace("QID", qid))
    if "OPT0" in str(payload):
        o0 = [o.key for o in get_question(qid).options][0]
        payload = json.loads(json.dumps(payload).replace("OPT0", o0))
    handler._response = json.dumps(payload).encode()

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert "out_of_schema" in caplog.text
    client.close()


def test_warning_text_never_contains_model_path(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    secret_path = "/secret/models/k1-evil.gguf"
    handler._props_response = {"model_path": secret_path}

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
    )
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert secret_path not in caplog.text
    client.close()


def test_identity_reverified_on_ttl(server, sidecar_path, caplog):
    url, _srv, handler = server
    qid = _first_id("noul")
    good = json.dumps(
        {"model": "k1-jev", "answers": {qid: {"type": "noul", "noul": 0.5}}, "usage": {}}
    ).encode()
    handler._response = good

    now = [0.0]

    def monotonic():
        return now[0]

    client = DecisionClient(
        DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path)),
        clock=monotonic,
    )

    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 1

    now[0] = 59.0
    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 1

    now[0] = 60.0
    assert client.ask("x", None, [qid]) is not None
    assert len(_props_requests(handler)) == 2

    handler._props_response = {"model_path": "/models/k1-evil.gguf"}
    now[0] = 120.0
    with caplog.at_level("WARNING"):
        assert client.ask("x", None, [qid]) is None
    assert len(_props_requests(handler)) == 3
    assert "identity_mismatch" in caplog.text

    client.close()


def test_string_numbers_rejected(server, sidecar_path):
    url, _srv, handler = server
    qid_noul = _first_id("noul")
    qid_score = _first_id("score")
    qid_choice = _first_id("choice")
    choice_key = get_question(qid_choice).options[0].key

    base = {"model": "k1-jev", "answers": {}, "usage": {}}
    cases = [
        (qid_noul, {"type": "noul", "noul": "0.5"}),
        (qid_score, {"type": "score", "score": "1"}),
        (qid_choice, {"type": "choice", "choice": choice_key, "probabilities": {choice_key: "0.3"}}),
    ]

    for qid, answer in cases:
        handler._response = json.dumps({**base, "answers": {qid: answer}}).encode()
        client = DecisionClient(
            DecisionConfig(enabled=True, url=url, thresholds_path=str(sidecar_path))
        )
        assert client.ask("x", None, [qid]) is None
        client.close()
