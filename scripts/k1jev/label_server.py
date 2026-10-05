# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local HTTP server for labelling K1-Jev gold examples."""

from __future__ import annotations

import argparse
import datetime
import hmac
import hashlib
import json
import os
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from math import ceil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from kaine.decision.schema import QUESTIONS, Option, get_question

MAX_BODY = 4096

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>K1-Jev labelling</title>
<style nonce="__NONCE__">
  body { font-family: sans-serif; max-width: 800px; margin: 1em auto; padding: 0 1em; line-height: 1.4; }
  h2 { font-size: 1.1em; margin: 0.5em 0; }
  h3 { font-size: 1em; margin: 0.5em 0; color: #555; }
  #utterance { background: #f4f4f4; padding: 0.8em; border-radius: 4px; white-space: pre-wrap; }
  #options { margin: 0.8em 0; }
  #options button, #extra button { display: block; width: 100%; margin: 0.3em 0; padding: 0.6em; text-align: left; cursor: pointer; }
  #extra button { background: #eee; }
  #progress { font-weight: bold; margin-bottom: 1em; }
</style>
</head>
<body>
<div id="progress"></div>
<div id="utterance"></div>
<div id="context-wrap"></div>
<div id="question"></div>
<div id="definition"></div>
<div id="options"></div>
<div id="extra">
  <button id="unsure">Unsure (u)</button>
  <button id="skip">Skip (s)</button>
  <button id="back">Back (b)</button>
</div>
<script nonce="__NONCE__">
const token = new URLSearchParams(location.search).get('t');
let currentItem = null;
let currentOptions = [];

async function api(path, method, body) {
  const init = { method: method || 'GET', headers: { 'X-Label-Token': token } };
  if (body) init.body = JSON.stringify(body);
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function optionLabel(opt) {
  if (opt.key === 'true') return 'Yes';
  if (opt.key === 'false') return 'No';
  if (opt.description) return opt.key + ': ' + opt.description;
  return opt.key;
}

function renderItem(data) {
  currentItem = data.item;
  document.getElementById('progress').textContent = data.progress.done + ' / ' + data.progress.total;
  if (!currentItem) {
    document.body.innerHTML = '<p>All done.</p>';
    return;
  }
  currentOptions = currentItem.options;
  document.getElementById('utterance').textContent = currentItem.utterance;
  const cw = document.getElementById('context-wrap');
  if (currentItem.context != null) {
    const label = currentItem.context_label ? ' (' + currentItem.context_label + ')' : '';
    cw.innerHTML = '<h3>Context' + label + '</h3><p>' + escapeHtml(currentItem.context) + '</p>';
  } else {
    cw.innerHTML = '';
  }
  document.getElementById('question').innerHTML = '<h2>' + escapeHtml(currentItem.instructions) + '</h2>';
  const defEl = document.getElementById('definition');
  if (currentItem.definition) {
    defEl.innerHTML = '<h3>Definition</h3><p>' + escapeHtml(currentItem.definition) + '</p>';
  } else {
    defEl.innerHTML = '';
  }
  const opts = document.getElementById('options');
  opts.innerHTML = '';
  currentItem.options.forEach(function(opt, idx) {
    const btn = document.createElement('button');
    btn.textContent = (idx + 1) + '. ' + optionLabel(opt);
    btn.onclick = function() { answer(opt.key, false); };
    opts.appendChild(btn);
  });
}

async function loadNext() {
  renderItem(await api('/api/next'));
}

async function answer(key, unsure) {
  if (!currentItem) return;
  await api('/api/answer', 'POST', { item_id: currentItem.item_id, label: unsure ? null : key, unsure: unsure });
  await loadNext();
}

async function skip() {
  if (!currentItem) return;
  await api('/api/skip', 'POST', { item_id: currentItem.item_id });
  await loadNext();
}

async function prev() {
  renderItem(await api('/api/prev'));
}

document.getElementById('unsure').onclick = function() { answer(null, true); };
document.getElementById('skip').onclick = skip;
document.getElementById('back').onclick = prev;

document.addEventListener('keydown', function(e) {
  const k = e.key;
  if (k >= '1' && k <= '9') {
    const idx = parseInt(k, 10) - 1;
    if (idx < currentOptions.length) answer(currentOptions[idx].key, false);
  } else if (k === 'u' || k === 'U') {
    answer(null, true);
  } else if (k === 's' || k === 'S') {
    skip();
  } else if (k === 'b' || k === 'B') {
    prev();
  }
});

loadNext();
</script>
</body>
</html>"""


def _load_items(path: Path) -> list[dict]:
    """Load and validate the gold items; refuse a file the page cannot serve."""
    known = {q.id for q in QUESTIONS}
    items: list[dict] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"{path} line {n}: an item must be a JSON object")
            iid = item.get("item_id")
            if not isinstance(iid, str) or not iid:
                raise ValueError(f"{path} line {n}: item_id must be a non-empty string")
            if iid in seen:
                raise ValueError(f"{path} line {n}: duplicate item_id {iid!r}")
            if item.get("question_id") not in known:
                raise ValueError(f"{path} line {n}: unknown question_id")
            if not isinstance(item.get("utterance"), str):
                raise ValueError(f"{path} line {n}: utterance must be a string")
            context = item.get("context")
            if context is not None and not isinstance(context, str):
                raise ValueError(f"{path} line {n}: context must be a string or null")
            seen.add(iid)
            items.append(item)
    return items


def _default_labels_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
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
    return git_common / "kaine-tools" / "k1jev" / "gold" / "labels.jsonl"


def _current_labels(labels_path: Path) -> dict[tuple[str, str], dict]:
    labels: dict[tuple[str, str], dict] = {}
    if not labels_path.exists():
        return labels
    with labels_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            labels[(record["item_id"], record["pass"])] = record
    return labels


def _repeat_subset(item_ids: list[str], fraction: float) -> set[str]:
    n = ceil(fraction * len(item_ids))
    digests = {iid: hashlib.sha256(iid.encode()).hexdigest() for iid in item_ids}
    return set(sorted(item_ids, key=lambda iid: digests[iid])[:n])


def _print_report(items: list[dict], labels_path: Path, fraction: float) -> None:
    labels = _current_labels(labels_path)
    item_ids = [it["item_id"] for it in items]
    repeat_ids = _repeat_subset(item_ids, fraction)
    counts = {q.id: 0 for q in QUESTIONS}
    unsure = 0
    for record in labels.values():
        if record.get("pass") == "first":
            counts[record["question_id"]] = counts.get(record["question_id"], 0) + 1
        if record.get("unsure"):
            unsure += 1
    print("First-pass labels per question:")
    for q in QUESTIONS:
        print(f"  {q.id}: {counts[q.id]}")
    print(f"Unsure labels: {unsure}")
    both = []
    disagree = []
    for iid in item_ids:
        first = labels.get((iid, "first"))
        repeat = labels.get((iid, "repeat"))
        if first and repeat:
            both.append(iid)
            if first.get("label") != repeat.get("label"):
                disagree.append(iid)
    if both:
        pct = (len(both) - len(disagree)) / len(both) * 100
        print(f"First/repeat agreement: {len(both) - len(disagree)}/{len(both)} ({pct:.1f}%)")
    else:
        print("First/repeat agreement: 0/0 (no items with both passes)")
    if disagree:
        print("Disagreeing item ids:")
        for iid in disagree:
            print(f"  {iid}")
    else:
        print("No disagreements.")


class LabelServer(HTTPServer):
    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        items: list[dict],
        labels_path: Path,
        repeat_fraction: float,
        token: str,
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.items = items
        self.item_by_id = {it["item_id"]: it for it in items}
        self.labels_path = labels_path
        self.repeat_fraction = repeat_fraction
        self.token = token
        self.total = len(items)
        self.repeat_count = ceil(self.repeat_fraction * self.total) if self.total else 0
        item_ids = list(self.item_by_id.keys())
        self.repeat_ids = tuple(sorted(item_ids, key=lambda iid: hashlib.sha256(iid.encode()).hexdigest())[: self.repeat_count])
        self.first_pass_queue = list(item_ids)
        self.repeat_pass_queue = list(self.repeat_ids)
        self.labels: dict[tuple[str, str], dict] = {}
        self.last_answered_key: tuple[str, str] | None = None
        self._ensure_labels_dir()
        self._load_labels()

    def _ensure_labels_dir(self) -> None:
        self.labels_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _load_labels(self) -> None:
        if not self.labels_path.exists():
            return
        with self.labels_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                key = (record["item_id"], record["pass"])
                self.labels[key] = record
                self.last_answered_key = key

    def first_pass_done(self) -> int:
        # Count only items in this items file, so stale lines from another
        # file can never make the first pass look complete.
        return sum(
            1 for (iid, pass_) in self.labels if pass_ == "first" and iid in self.item_by_id
        )

    def next_item(self):
        progress = {"done": self.first_pass_done(), "total": self.total}
        for iid in self.first_pass_queue:
            if (iid, "first") not in self.labels:
                return self.item_by_id[iid], progress
        for iid in self.repeat_pass_queue:
            if (iid, "repeat") not in self.labels:
                return self.item_by_id[iid], progress
        return None, progress

    def _move_to_end(self, queue: list[str], iid: str) -> None:
        try:
            queue.remove(iid)
        except ValueError:
            pass
        queue.append(iid)

    def skip(self, iid: str) -> None:
        if self.total == 0:
            return
        if self.first_pass_done() < self.total:
            self._move_to_end(self.first_pass_queue, iid)
        else:
            self._move_to_end(self.repeat_pass_queue, iid)

    def answer(self, iid: str, label, unsure: bool) -> None:
        item = self.item_by_id[iid]
        question = get_question(item["question_id"])
        valid_keys = {opt.key for opt in question.options}
        if unsure:
            if label is not None:
                raise ValueError("label must be null when unsure is true")
        else:
            if label not in valid_keys:
                raise ValueError(f"invalid label {label!r}")
        # The repeat pass starts only once every item has a first-pass label, so
        # revising a first-pass answer with "Back" never counts as a repeat.
        if self.first_pass_done() >= self.total and iid in self.repeat_ids:
            pass_ = "repeat"
        else:
            pass_ = "first"
        record = {
            "item_id": iid,
            "question_id": item["question_id"],
            "label": label,
            "unsure": unsure,
            "pass": pass_,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._append_label(record)

    def _append_label(self, record: dict) -> None:
        # Persist first; only a label that reached the disk counts as given.
        self._ensure_labels_dir()
        with self.labels_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        key = (record["item_id"], record["pass"])
        self.labels[key] = record
        self.last_answered_key = key

    def prev_item(self):
        progress = {"done": self.first_pass_done(), "total": self.total}
        if self.last_answered_key is None or self.last_answered_key not in self.labels:
            return None, progress
        iid = self.last_answered_key[0]
        return self.item_by_id[iid], progress


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _security_headers(self, nonce: str):
        csp = (
            f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'"
        )
        return {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": csp,
        }

    def _send(self, code, body, content_type, nonce=None):
        if nonce is None:
            nonce = secrets.token_urlsafe(16)
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        for name, value in self._security_headers(nonce).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(200, body, "application/json")

    def _check_host(self):
        host = self.headers.get("Host")
        ok = (
            host == f"127.0.0.1:{self.server.server_port}"
            or host == f"localhost:{self.server.server_port}"
        )
        if not ok:
            self._send(403, b"", "text/plain")
            return False
        return True

    def _check_token(self, token):
        if token is None or not hmac.compare_digest(token, self.server.token):
            self._send(403, b"", "text/plain")
            return False
        return True

    def _read_body(self):
        length = self.headers.get("Content-Length")
        if length is None:
            self._send(411, b"", "text/plain")
            return None
        try:
            n = int(length)
        except ValueError:
            self._send(400, b"", "text/plain")
            return None
        if n < 0:
            self._send(400, b"", "text/plain")
            return None
        if n > MAX_BODY:
            self._send(413, b"", "text/plain")
            return None
        return self.rfile.read(n)

    def _allowlisted(self, item):
        question = get_question(item["question_id"])
        return {
            "item_id": item["item_id"],
            "question_id": item["question_id"],
            "utterance": item["utterance"],
            "context": item.get("context"),
            "instructions": question.instructions,
            "definition": question.definition,
            "context_label": question.context_label,
            "options": [{"key": opt.key, "description": opt.description} for opt in question.options],
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            if not self._check_host():
                return
            token = parse_qs(parsed.query).get("t", [""])[0]
            if not self._check_token(token):
                return
            nonce = secrets.token_urlsafe(16)
            html = PAGE_HTML.replace("__NONCE__", nonce)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8", nonce=nonce)
        elif parsed.path == "/api/next":
            if not self._check_host():
                return
            if not self._check_token(self.headers.get("X-Label-Token")):
                return
            item, progress = self.server.next_item()
            payload = {"item": self._allowlisted(item) if item else None, "progress": progress}
            self._send_json(payload)
        elif parsed.path == "/api/prev":
            if not self._check_host():
                return
            if not self._check_token(self.headers.get("X-Label-Token")):
                return
            item, progress = self.server.prev_item()
            payload = {"item": self._allowlisted(item) if item else None, "progress": progress}
            self._send_json(payload)
        else:
            self._send(404, b"", "text/plain")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/answer", "/api/skip"):
            self._send(404, b"", "text/plain")
            return
        if not self._check_host():
            return
        if not self._check_token(self.headers.get("X-Label-Token")):
            return
        body = self._read_body()
        if body is None:
            return
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send(400, b"", "text/plain")
            return
        if not isinstance(payload, dict):
            self._send(400, b"", "text/plain")
            return
        if parsed.path == "/api/answer":
            try:
                iid = payload["item_id"]
                label = payload.get("label")
                unsure = bool(payload.get("unsure", False))
                self.server.answer(iid, label, unsure)
            except (KeyError, ValueError, TypeError):
                self._send(400, b"", "text/plain")
                return
            self._send_json({"ok": True})
        elif parsed.path == "/api/skip":
            try:
                iid = payload["item_id"]
            except KeyError:
                self._send(400, b"", "text/plain")
                return
            if not isinstance(iid, str) or iid not in self.server.item_by_id:
                self._send(400, b"", "text/plain")
                return
            self.server.skip(iid)
            self._send_json({"ok": True})


def make_server(
    items_path,
    labels_path,
    *,
    bind="127.0.0.1",
    port=0,
    repeat_fraction=0.10,
    token=None,
):
    if bind != "127.0.0.1":
        raise ValueError(f"refusing to bind to {bind!r}; only 127.0.0.1 is allowed")
    if not 0.0 <= float(repeat_fraction) <= 1.0:
        raise ValueError(f"repeat_fraction must be between 0 and 1, got {repeat_fraction!r}")
    items = _load_items(Path(items_path))
    labels_path = Path(labels_path)
    if token is None:
        token = secrets.token_urlsafe(16)
    server = LabelServer(
        (bind, port),
        _Handler,
        items,
        labels_path,
        repeat_fraction,
        token,
    )
    return server, token


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="K1-Jev local labelling server")
    parser.add_argument("--items", required=True, type=Path)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--repeat-fraction", type=float, default=0.10)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    labels_path = args.labels if args.labels else _default_labels_path()
    items = _load_items(args.items)
    if args.report:
        _print_report(items, labels_path, args.repeat_fraction)
        return 0
    try:
        server, token = make_server(
            args.items,
            labels_path,
            bind=args.bind,
            port=args.port,
            repeat_fraction=args.repeat_fraction,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"labelling page: http://127.0.0.1:{server.server_port}/?t={token}")
    print(f"items: {server.total}, repeat subset: {server.repeat_count}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
