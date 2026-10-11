# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev local labelling server."""

import http.client
import importlib.util
import json
import subprocess
import sys
import threading
from math import ceil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_LABEL_SERVER_SPEC = importlib.util.spec_from_file_location(
    "label_server", REPO_ROOT / "scripts" / "k1jev" / "label_server.py"
)
label_server = importlib.util.module_from_spec(_LABEL_SERVER_SPEC)
sys.modules["label_server"] = label_server
_LABEL_SERVER_SPEC.loader.exec_module(label_server)


def _write_items(path, n, marker=None):
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            item = {
                "item_id": f"item-{i:03d}",
                "question_id": "declined",
                "utterance": f"Utterance {i}",
            }
            if marker:
                item["generated_label"] = f"generated-{marker}-{i}"
                item["category"] = f"category-{marker}-{i}"
                item["template"] = f"template-{marker}-{i}"
            f.write(json.dumps(item) + "\n")


def _start(server):
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def _conn(port):
    return http.client.HTTPConnection("127.0.0.1", port)


def _api(conn, method, path, body=None, token=None, extra_headers=None):
    headers = {}
    if token is not None:
        headers["X-Label-Token"] = token
    if extra_headers:
        headers.update(extra_headers)
    if body is not None and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)


def _read_json(resp):
    return json.loads(resp.read().decode("utf-8"))


def test_make_server_refuses_nonlocal_bind(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 1)
    with pytest.raises((SystemExit, ValueError)):
        label_server.make_server(items, labels, bind="0.0.0.0")


def test_main_refuses_nonlocal_bind(tmp_path):
    items = tmp_path / "items.jsonl"
    _write_items(items, 1)
    assert label_server.main(["--items", str(items), "--bind", "0.0.0.0"]) == 2


def test_token_and_host_checks(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 2)
    server, token = label_server.make_server(items, labels)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "GET", "/api/next")
        assert c.getresponse().status == 403

        c = _conn(server.server_port)
        _api(c, "GET", "/api/next", token="bad-token")
        assert c.getresponse().status == 403

        c = _conn(server.server_port)
        _api(
            c,
            "GET",
            "/api/next",
            token=token,
            extra_headers={"Host": f"evil.example:{server.server_port}"},
        )
        assert c.getresponse().status == 403
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_root_page(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 1)
    server, token = label_server.make_server(items, labels)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        c.request("GET", f"/?t={token}")
        resp = c.getresponse()
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "http://" not in body
        assert "https://" not in body
        assert resp.getheader("Content-Security-Policy") is not None
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_blindness(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    marker = "blindness_marker_xyz_12345"
    _write_items(items, 2, marker=marker)
    server, token = label_server.make_server(items, labels)
    t = _start(server)
    try:
        c = _conn(server.server_port)

        _api(c, "GET", "/api/next", token=token)
        next_resp = _read_json(c.getresponse())
        combined = json.dumps(next_resp)
        assert marker not in combined

        c.request("GET", f"/?t={token}")
        page = c.getresponse().read().decode("utf-8")
        assert marker not in page

        item = next_resp["item"]
        _api(
            c,
            "POST",
            "/api/answer",
            body={"item_id": item["item_id"], "label": "false", "unsure": False},
            token=token,
        )
        assert c.getresponse().status == 200

        _api(c, "GET", "/api/prev", token=token)
        prev_resp = _read_json(c.getresponse())
        combined = json.dumps(prev_resp)
        assert marker not in combined
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_answer_writes_fsynced_line_and_resumes(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 2)
    server, token = label_server.make_server(items, labels)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "GET", "/api/next", token=token)
        item = _read_json(c.getresponse())["item"]

        _api(
            c,
            "POST",
            "/api/answer",
            body={"item_id": item["item_id"], "label": "false", "unsure": False},
            token=token,
        )
        assert c.getresponse().status == 200

        lines = list(labels.open("r", encoding="utf-8"))
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["item_id"] == item["item_id"]
        assert record["pass"] == "first"
    finally:
        server.shutdown()
        server.server_close()
        t.join()

    server2, token2 = label_server.make_server(items, labels)
    t2 = _start(server2)
    try:
        c = _conn(server2.server_port)
        _api(c, "GET", "/api/next", token=token2)
        item2 = _read_json(c.getresponse())["item"]
        assert item2["item_id"] != item["item_id"]
    finally:
        server2.shutdown()
        server2.server_close()
        t2.join()


def test_invalid_label(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 1)
    server, token = label_server.make_server(items, labels)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "GET", "/api/next", token=token)
        item = _read_json(c.getresponse())["item"]

        _api(
            c,
            "POST",
            "/api/answer",
            body={"item_id": item["item_id"], "label": "not_an_option", "unsure": False},
            token=token,
        )
        assert c.getresponse().status == 400
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_repeat_pass(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    n = 10
    fraction = 0.2
    _write_items(items, n)
    server, token = label_server.make_server(items, labels, repeat_fraction=fraction)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        for _ in range(n):
            _api(c, "GET", "/api/next", token=token)
            item = _read_json(c.getresponse())["item"]
            _api(
                c,
                "POST",
                "/api/answer",
                body={"item_id": item["item_id"], "label": "false", "unsure": False},
                token=token,
            )
            assert c.getresponse().status == 200

        repeat_count = 0
        while True:
            _api(c, "GET", "/api/next", token=token)
            resp = _read_json(c.getresponse())
            if resp["item"] is None:
                break
            repeat_count += 1
            item = resp["item"]
            _api(
                c,
                "POST",
                "/api/answer",
                body={"item_id": item["item_id"], "label": "true", "unsure": False},
                token=token,
            )
            assert c.getresponse().status == 200

        assert repeat_count == ceil(n * fraction)

        repeat_labels = 0
        for line in labels.open("r", encoding="utf-8"):
            record = json.loads(line)
            if record.get("pass") == "repeat":
                repeat_labels += 1
        assert repeat_labels == repeat_count
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_body_too_large(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 1)
    server, token = label_server.make_server(items, labels)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "GET", "/api/next", token=token)
        item = _read_json(c.getresponse())["item"]

        big_body = json.dumps({"item_id": item["item_id"], "label": "false", "unsure": False}) + "x" * 4096
        _api(
            c,
            "POST",
            "/api/answer",
            body=None,
            token=token,
            extra_headers={"Content-Type": "application/json", "Content-Length": str(len(big_body))},
        )
        c.send(big_body.encode("utf-8"))
        resp = c.getresponse()
        assert resp.status == 413
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_default_labels_path_inside_git_common_dir():
    default = label_server._default_labels_path()
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_root),
    )
    git_common = Path(result.stdout.strip())
    if not git_common.is_absolute():
        git_common = (repo_root / git_common).resolve()
    assert str(default).startswith(str(git_common))
    assert "kaine-tools" in str(default)


def test_revising_a_first_pass_answer_is_never_a_repeat(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 10)
    server, token = label_server.make_server(items, labels, repeat_fraction=1.0)
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "GET", "/api/next", token=token)
        item = _read_json(c.getresponse())["item"]
        for label in ("false", "true"):  # answer, then revise the same item
            _api(
                c,
                "POST",
                "/api/answer",
                body={"item_id": item["item_id"], "label": label, "unsure": False},
                token=token,
            )
            assert c.getresponse().status == 200
        passes = [json.loads(line)["pass"] for line in labels.open(encoding="utf-8")]
        assert passes == ["first", "first"]
    finally:
        server.shutdown()
        server.server_close()
        t.join()


@pytest.mark.parametrize(
    "bad_line",
    [
        '{"item_id": "a", "question_id": "no_such_question", "utterance": "x"}',
        '{"question_id": "declined", "utterance": "x"}',
        '{"item_id": "a", "question_id": "declined", "utterance": 5}',
        '["not", "an", "object"]',
    ],
)
def test_invalid_items_file_refused_at_start(tmp_path, bad_line):
    items = tmp_path / "items.jsonl"
    items.write_text(bad_line + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        label_server.make_server(items, tmp_path / "labels.jsonl")


def test_duplicate_item_ids_refused(tmp_path):
    items = tmp_path / "items.jsonl"
    line = json.dumps({"item_id": "a", "question_id": "declined", "utterance": "x"})
    items.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        label_server.make_server(items, tmp_path / "labels.jsonl")


def test_non_string_item_id_is_a_400(tmp_path):
    items = tmp_path / "items.jsonl"
    _write_items(items, 2)
    server, token = label_server.make_server(items, tmp_path / "labels.jsonl")
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "POST", "/api/answer", body={"item_id": ["x"], "label": "true"}, token=token)
        assert c.getresponse().status == 400
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_negative_content_length_is_refused(tmp_path):
    items = tmp_path / "items.jsonl"
    _write_items(items, 2)
    server, token = label_server.make_server(items, tmp_path / "labels.jsonl")
    t = _start(server)
    try:
        c = _conn(server.server_port)
        c.putrequest("POST", "/api/answer")
        c.putheader("X-Label-Token", token)
        c.putheader("Content-Length", "-1")
        c.endheaders()
        assert c.getresponse().status == 400
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_non_object_body_is_a_400(tmp_path):
    items = tmp_path / "items.jsonl"
    _write_items(items, 2)
    server, token = label_server.make_server(items, tmp_path / "labels.jsonl")
    t = _start(server)
    try:
        c = _conn(server.server_port)
        _api(c, "POST", "/api/skip", body=["item-000"], token=token)
        assert c.getresponse().status == 400
    finally:
        server.shutdown()
        server.server_close()
        t.join()


@pytest.mark.parametrize("fraction", [-0.1, 1.5])
def test_repeat_fraction_out_of_range_is_refused(tmp_path, fraction):
    items = tmp_path / "items.jsonl"
    _write_items(items, 2)
    with pytest.raises(ValueError):
        label_server.make_server(items, tmp_path / "labels.jsonl", repeat_fraction=fraction)


def test_stale_labels_for_unknown_items_do_not_finish_the_first_pass(tmp_path):
    items = tmp_path / "items.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_items(items, 2)
    labels.write_text(
        "".join(
            json.dumps({"item_id": f"other-{i}", "question_id": "declined", "label": "true",
                        "unsure": False, "pass": "first", "ts": "x"}) + "\n"
            for i in range(5)
        ),
        encoding="utf-8",
    )
    server, _token = label_server.make_server(items, labels, repeat_fraction=1.0)
    try:
        assert server.first_pass_done() == 0
        item, _ = server.next_item()
        assert item["item_id"] == "item-000"
    finally:
        server.server_close()

