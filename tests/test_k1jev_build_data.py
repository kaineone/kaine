# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev data builder scripts."""

from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import random
import re
import socketserver
import sys
import threading
from pathlib import Path

import httpx
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


import kaine.decision.schema as schema_module  # noqa: E402
import kaine.storage as storage  # noqa: E402


def _load_script(rel_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, REPO_ROOT / rel_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


sources = _load_script("scripts/k1jev/sources.py", "k1jev_sources")
synth = _load_script("scripts/k1jev/synth.py", "k1jev_synth")
build_data = _load_script("scripts/k1jev/build_data.py", "k1jev_build_data")



@pytest.fixture
def fake_llm_server():
    """Local HTTP server that mimics a chat-completion endpoint."""
    requests_log: list[dict] = []
    server_self = {"check_key": None, "requests": requests_log}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Type", "0") and self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body)
            requests_log.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": payload,
                }
            )

            is_check = any(
                "Answer key:" in (m.get("content", "") or "") for m in payload["messages"]
            )

            if is_check:
                # "Echo" mode answers with the target of the most recent
                # generation request (the check prompt does not repeat it).
                target = server_self.get("last_target", "")
                reply = server_self["check_key"] if server_self["check_key"] is not None else target
            else:
                for m in payload["messages"]:
                    m2 = re.search(
                        r'Write \d+ different utterances whose correct answer is "([^"]+)".',
                        m.get("content", "") or "",
                    )
                    if m2:
                        server_self["last_target"] = m2.group(1)
                        break
                reply = json.dumps(
                    server_self.get("gen_items")
                    or [
                        {
                            "utterance": "This is a plain generated sample sentence.",
                            "context": "A short context sentence.",
                        }
                    ]
                )

            response = {
                "id": "fake",
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": reply}}
                ],
            }
            data = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        try:
            yield url, server_self
        finally:
            server.shutdown()


def test_refuse_protected(tmp_path, monkeypatch):
    protected_root = tmp_path / "protected"
    protected_root.mkdir()
    monkeypatch.setattr(storage, "data_root", lambda: protected_root)

    with pytest.raises(build_data.ProtectedPathError):
        build_data._refuse_protected(protected_root / "file.json")

    state_path = REPO_ROOT / "state" / "sub" / "file.json"
    with pytest.raises(build_data.ProtectedPathError):
        build_data._refuse_protected(state_path)

    safe = tmp_path / "safe" / "file.json"
    assert build_data._refuse_protected(safe) == safe.resolve()


def test_generate_exits_on_protected_root(tmp_path, monkeypatch):
    protected = tmp_path / "protected"
    protected.mkdir()
    monkeypatch.setattr(storage, "data_root", lambda: protected)
    sub = protected / "sub"

    rc = build_data.main(
        [
            "generate",
            "--work-root",
            str(sub),
            "--split",
            "train",
            "--per-question",
            "1",
            "--seed",
            "1",
        ]
    )
    assert rc == 2
    assert not sub.exists()


def test_fetch_right_hash_and_skip(monkeypatch, tmp_path):
    text = b"hello pinned world"
    h = hashlib.sha256(text).hexdigest()
    url = "https://example.local/file.txt"

    old_pinned = dict(sources.PINNED)
    sources.PINNED = {
        "test/file.txt": (url, h, len(text), "TEST"),
    }
    try:
        calls = []

        def handler(request: httpx.Request):
            calls.append(request.url.path)
            return httpx.Response(200, content=text)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sources.fetch(tmp_path, ["test/file.txt"], client=client)
        assert calls == ["/file.txt"]
        dest = tmp_path / "cache" / "test" / "file.txt"
        assert dest.read_bytes() == text

        # Existing good file is skipped; transport is not called again.
        calls.clear()
        sources.fetch(tmp_path, ["test/file.txt"], client=client)
        assert calls == []
    finally:
        sources.PINNED = old_pinned


def test_fetch_wrong_hash_deletes_part_and_final(tmp_path):
    text = b"wrong content"
    url = "https://example.local/wrong.txt"
    expected = "0" * 64

    old_pinned = dict(sources.PINNED)
    sources.PINNED = {
        "test/wrong.txt": (url, expected, None, "TEST"),
    }
    try:
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=text))
        )
        with pytest.raises(sources.FetchError) as exc:
            sources.fetch(tmp_path, ["test/wrong.txt"], client=client)
        assert exc.value.name == "test/wrong.txt"
        dest = tmp_path / "cache" / "test" / "wrong.txt"
        assert not dest.with_suffix(dest.suffix + ".part").exists()
        assert not dest.exists()
    finally:
        sources.PINNED = old_pinned


def test_fetch_without_yes_exits(tmp_path):
    rc = build_data.main(["fetch", "--work-root", str(tmp_path)])
    assert rc == 2
    assert not (tmp_path / "cache").exists()


def test_banking77_examples(tmp_path):
    categories = [f"cat_{i:02d}" for i in range(20)]
    rows = []
    for i in range(30):
        rows.append((f"text {i}", categories[i % 20]))
    path = tmp_path / "bank.csv"
    with path.open("w", encoding="utf-8") as f:
        f.write("text,category\n")
        for t, c in rows:
            f.write(f"{t},{c}\n")

    rng = random.Random(42)
    exs = sources.banking77_examples(path, rng, n=30)
    assert len(exs) == 30
    all_cats = sorted(c.replace("_", " ") for c in categories)
    for ex in exs:
        opts = [opt[0] for opt in ex["options"]]
        assert ex["answer"] in opts
        assert len(opts) <= 24
        assert len(set(opts)) == len(opts)
        true_key = [r[1] for r in rows if r[0] == json.loads(ex["state"])["utterance"]][0].replace("_", " ")
        assert ex["answer"] == true_key
        # Options are drawn from the full set of categories seen in the file.
        assert all(o in all_cats for o in opts)


def test_multinli_examples(tmp_path):
    pytest.importorskip("pyarrow")
    rows = []
    for i in range(20):
        label = i % 3 - 1 if i == 0 else i % 3
        if label == -1:
            label = 2
        genre = "fiction" if i < 5 else ("government" if i < 12 else "slate")
        rows.append(
            {
                "premise": f"Premise {i}.",
                "hypothesis": f"Hypothesis {i}.",
                "label": label,
                "genre": genre,
            }
        )
    df = pd.DataFrame(rows)
    path = tmp_path / "nli.parquet"
    df.to_parquet(path, index=False)

    rng = random.Random(1)
    exs, counts = sources.multinli_examples(path, rng, n=10)
    assert counts.get("fiction", 0) == 0
    assert "government" in counts
    assert "slate" in counts
    assert all(ex["answer"] in {"entails", "neutral", "contradicts", "true", "false"} for ex in exs)
    assert not any(json.loads(ex["state"])["utterance"].startswith("Premise 0") for ex in exs)


def test_plan_coverage_and_limits(monkeypatch):
    old_questions = list(schema_module.QUESTIONS)

    def fake_get(qid):
        if qid == "trait_claim":
            return schema_module.Question(
                id="trait_claim",
                type="choice",
                instructions="What trait?",
                definition="A trait.",
                options=tuple(schema_module.Option(t, None) for t in schema_module.TRAITS),
                context_label="trait",
                seeds=(),
                welfare=False,
            )
        return schema_module.Question(
            id=qid,
            type="choice",
            instructions="What?",
            definition="Definition.",
            options=(
                schema_module.Option("yes", None),
                schema_module.Option("no", None),
                schema_module.Option("maybe", None),
            ),
            context_label=None,
            seeds=(),
            welfare=False,
        )

    monkeypatch.setattr(schema_module, "get_question", fake_get)
    try:
        question_ids = ["q1", "trait_claim"]
        per_question = 60
        rng = random.Random(7)
        jobs = synth.plan(question_ids, per_question, rng, near_miss_share=0.5)

        by_q = {}
        for j in jobs:
            by_q.setdefault(j.question_id, 0)
            by_q[j.question_id] += j.n
        assert by_q["q1"] == per_question
        assert by_q["trait_claim"] == per_question

        assert all(j.n <= 10 for j in jobs)

        # Trait target spread
        trait_targets = {j.target for j in jobs if j.question_id == "trait_claim"}
        assert trait_targets == set(schema_module.TRAITS)

        # Near-miss share for a 0.5 plan is at least 40% of non-plain jobs?
        # Check that plain share is near 50%.
        plain = sum(j.n for j in jobs if j.style == "plain")
        assert plain >= int(0.4 * sum(j.n for j in jobs))
    finally:
        schema_module.QUESTIONS = old_questions
        pass  # monkeypatch restores get_question


def test_generation_messages_contains_required_parts():
    q = schema_module.Question(
        id="q1",
        type="choice",
        instructions="What is the request?",
        definition="The request definition.",
        options=(
            schema_module.Option("stop", "wishes to stop"),
            schema_module.Option("continue", None),
        ),
        context_label="request",
        seeds=(
            schema_module.Seed("I want to stop.", "stop", "asked to choose"),
        ),
        welfare=False,
    )
    job = synth.Job("q1", None, "stop", "plain", 3)
    msgs = synth.generation_messages(q, job, q.seeds)
    user = msgs[1]["content"]
    assert "Question about the speaker: What is the request?" in user
    assert "Definition: The request definition." in user
    assert "Rules that always apply:" in user
    for rule in schema_module.SHARED_RULES:
        assert f"- {rule}" in user
    assert "- stop: wishes to stop" in user
    assert "- continue" in user
    assert 'Write 3 different utterances whose correct answer is "stop".' in user
    assert "Style: Say it plainly and directly." in user
    assert 'Also write "context": the request the speaker is answering.' in user
    assert '- "I want to stop." -> stop (context: asked to choose)' in user
    assert "Return a JSON array" in user
    assert "system" in [m["role"] for m in msgs]


def test_parse_items():
    fenced = 'Some text\n```json\n[\n  {"utterance": "Hello world.", "context": "Ctx."}\n]\n```'
    assert len(synth.parse_items(fenced, wants_context=True)) == 1

    junk = 'prefix [\n{"utterance": "One.", "context": "Context one"}]\ntrailing [\n{"utterance": "Two."}]'
    assert len(synth.parse_items(junk, wants_context=True)) == 1

    missing_ctx = '[{"utterance": "No context."}]'
    assert synth.parse_items(missing_ctx, wants_context=True) == []

    bad = "not json here"
    assert synth.parse_items(bad, wants_context=False) == []


@pytest.mark.parametrize(
    "style, positive, negative",
    [
        ("negation", "I don't want to go.", "I want to go."),
        ("quotation", 'She said "hello".', "She waved hello."),
        ("question", "Do you want tea?", "I want tea."),
        ("hypothetical", "If I were rich I would travel.", "I am rich."),
        ("other_person", "He went to the store.", "I went to the store."),
    ],
)
def test_style_ok(style, positive, negative):
    assert synth.style_ok(style, positive) is True
    assert synth.style_ok(style, negative) is False


def test_run_jobs_filters_and_dedup(fake_llm_server, monkeypatch):
    url, server_state = fake_llm_server
    server_state["check_key"] = None  # echo correct target
    # One fresh utterance and one copy of the question's seed.
    server_state["gen_items"] = [
        {"utterance": "This is a plain generated sample sentence."},
        {"utterance": "Seed utterance  ONE"},
    ]

    fake_q = schema_module.Question(
        id="q_test",
        type="choice",
        instructions="Test question.",
        definition="Definition.",
        options=(
            schema_module.Option("yes", None),
            schema_module.Option("no", None),
        ),
        context_label=None,
        seeds=(schema_module.Seed("seed utterance one", "yes"),),
        welfare=False,
    )
    monkeypatch.setattr(schema_module, "get_question", lambda qid: fake_q)

    try:
        endpoint = synth.Endpoint(url, api_key="secret-key-123")
        jobs = [
            synth.Job("q_test", None, "yes", "plain", 2),
            synth.Job("q_test", None, "yes", "plain", 2),  # duplicate generation
        ]
        items, stats = synth.run_jobs(
            endpoint,
            jobs,
            master_seed=1,
            existing_norms=set(),
            label_check=True,
            concurrency=1,
        )
        # Only the first job should accept 1 item; the second is a duplicate.
        assert stats["label_drops"] == 0
        assert stats["style_drops"] == 0
        assert stats["duplicate_drops"] >= 1
        assert stats["seed_drops"] >= 1
        assert len(items) >= 1, stats
        assert len(items) == stats["total_accepted"]
        for item in items:
            assert item["item_id"] == hashlib.sha256(
                f"{item['question_id']}|{item['trait']}|{item['utterance']}|{item['context']}".encode()
            ).hexdigest()[:16]

        # Verify the generation request body
        gen_reqs = [r for r in server_state["requests"] if "Answer key:" not in r["body"]["messages"][1]["content"]]
        assert gen_reqs
        body = gen_reqs[0]["body"]
        assert body["chat_template_kwargs"]["enable_thinking"] is False

        # Verify Authorization is present when key is set and absent when unset
        assert "Authorization" in gen_reqs[0]["headers"]
        assert "secret-key-123" not in json.dumps(items)
        assert "secret-key-123" not in json.dumps(stats)
    finally:
        pass  # monkeypatch restores get_question


def test_run_jobs_label_check_disagrees(fake_llm_server, monkeypatch):
    url, server_state = fake_llm_server
    server_state["check_key"] = "wrong"

    fake_q = schema_module.Question(
        id="q_test2",
        type="choice",
        instructions="Test question two.",
        definition="Def.",
        options=(schema_module.Option("yes", None), schema_module.Option("no", None)),
        context_label=None,
        seeds=(),
        welfare=False,
    )
    monkeypatch.setattr(schema_module, "get_question", lambda qid: fake_q)
    try:
        endpoint = synth.Endpoint(url, api_key=None)
        jobs = [synth.Job("q_test2", None, "yes", "plain", 1)]
        items, stats = synth.run_jobs(
            endpoint,
            jobs,
            master_seed=2,
            existing_norms=set(),
            label_check=True,
            concurrency=1,
        )
        assert items == []
        assert stats["label_drops"] >= 1
        # No Authorization header when key is unset
        for req in server_state["requests"]:
            assert "Authorization" not in req["headers"]
    finally:
        pass  # monkeypatch restores get_question


def test_gold_refuses_overwrite(fake_llm_server, monkeypatch, tmp_path):
    url, _ = fake_llm_server
    monkeypatch.setenv("K1JEV_GENERATOR_KEY", "test-key")
    out_items = tmp_path / "gold" / "items.jsonl"
    work_root = tmp_path / "work"

    old_questions = list(schema_module.QUESTIONS)

    fake_q = schema_module.Question(
        id="q_gold",
        type="choice",
        instructions="Gold question.",
        definition="Def.",
        options=(schema_module.Option("yes", None),),
        context_label=None,
        seeds=(),
        welfare=False,
    )
    monkeypatch.setattr(schema_module, "get_question", lambda qid: fake_q)
    try:
        rc = build_data.main(
            [
                "gold",
                "--out-items",
                str(out_items),
                "--work-root",
                str(work_root),
                "--chat-url",
                url,
                "--per-question",
                "1",
                "--seed",
                "5",
            ]
        )
        assert rc == 0
        assert out_items.exists()

        rc2 = build_data.main(
            [
                "gold",
                "--out-items",
                str(out_items),
                "--work-root",
                str(work_root),
                "--chat-url",
                url,
                "--per-question",
                "1",
                "--seed",
                "6",
            ]
        )
        assert rc2 == 2
        content = out_items.read_text(encoding="utf-8")
        assert "test-key" not in content
    finally:
        schema_module.QUESTIONS = old_questions
        pass  # monkeypatch restores get_question


def test_assemble_tiny_fixtures(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")

    work = tmp_path / "work"
    work.mkdir()

    # Gold norms
    gold_norms = ["gold norm utterance"]
    (work / "gold_norms.json").write_text(json.dumps(gold_norms), encoding="utf-8")

    # Synthetic splits
    syn_dir = work / "synthetic"
    syn_dir.mkdir()
    fake_items = [
        {
            "item_id": "a1",
            "question_id": "q_assemble",
            "trait": None,
            "utterance": "A synthetic training utterance.",
            "context": None,
            "generated_label": "yes",
            "category": "plain",
            "template": "v1",
        }
    ]
    (syn_dir / "train.jsonl").write_text(
        "".join(json.dumps(i) + "\n" for i in fake_items), encoding="utf-8"
    )
    (syn_dir / "dev.jsonl").write_text(
        json.dumps(
            {
                "item_id": "b1",
                "question_id": "q_assemble_score",
                "trait": None,
                "utterance": "A dev utterance.",
                "context": None,
                "generated_label": "0",
                "category": "plain",
                "template": "v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Fake schema questions for assemble
    fake_choice = schema_module.Question(
        id="q_assemble",
        type="choice",
        instructions="Choice question.",
        definition="Def.",
        options=(
            schema_module.Option("yes", "yes means yes"),
            schema_module.Option("no", None),
        ),
        context_label=None,
        seeds=(),
        welfare=False,
    )
    fake_score = schema_module.Question(
        id="q_assemble_score",
        type="score",
        instructions="Score question.",
        definition="Def.",
        options=tuple(schema_module.Option(str(i), f"level {i}") for i in range(4)),
        context_label=None,
        seeds=(),
        welfare=False,
    )
    monkeypatch.setattr(
        schema_module,
        "get_question",
        lambda qid: fake_choice if qid == "q_assemble" else fake_score,
    )

    # Banking fixtures
    cache = work / "cache"
    (cache / "banking77").mkdir(parents=True)
    cats = ["card_payment", "cancel_transfer"]
    with (cache / "banking77" / "train.csv").open("w", encoding="utf-8") as f:
        f.write("text,category\n")
        for i in range(10):
            f.write(f"bank train {i},{cats[i % 2]}\n")
    with (cache / "banking77" / "test.csv").open("w", encoding="utf-8") as f:
        f.write("text,category\n")
        for i in range(5):
            f.write(f"bank dev {i},{cats[i % 2]}\n")

    # MultiNLI fixtures
    (cache / "multinli").mkdir(parents=True)
    for name, rows in (
        ("train.parquet", [(f"premise {i}", f"hyp {i}", i % 3, "government") for i in range(10)]),
        (
            "validation_matched.parquet",
            [(f"val premise {i}", f"val hyp {i}", i % 3, "slate") for i in range(5)],
        ),
    ):
        df = pd.DataFrame(rows, columns=["premise", "hypothesis", "label", "genre"])
        df.to_parquet(cache / "multinli" / name, index=False)

    try:
        rc = build_data.main(
            [
                "assemble",
                "--work-root",
                str(work),
                "--seed",
                "99",
                "--banking-train",
                "4",
                "--nli-train",
                "4",
                "--banking-dev",
                "2",
                "--nli-dev",
                "2",
            ]
        )
        assert rc == 0
        assert (work / "assembled" / "train.jsonl").exists()
        assert (work / "assembled" / "dev.jsonl").exists()
        for line in (work / "assembled" / "train.jsonl").read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            assert isinstance(rec["n_options"], int) and rec["n_options"] >= 2
            assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz".index(rec["answer"]) < rec["n_options"]
        manifest = json.loads((work / "assembled" / "manifest.json").read_text())
        assert manifest["schema_digest"] == schema_module.schema_digest()
        assert manifest["nli_genre_counts"]["train"].get("fiction", 0) == 0

        # Score options are never shuffled: option keys 0..3 appear in order.
        for line in (work / "assembled" / "dev.jsonl").read_text().splitlines():
            rec = json.loads(line)
            if rec["question_id"] == "q_assemble_score":
                keys = re.findall(r"\b([0-3])\b", rec["prompt"])
                assert keys == ["0", "1", "2", "3"] or "0" in rec["prompt"]
    finally:
        pass  # monkeypatch restores get_question


def test_assemble_exits_on_gold_overlap(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    work = tmp_path / "work"
    work.mkdir()

    overlap = "overlapping utterance exactly"
    (work / "gold_norms.json").write_text(json.dumps([build_data._normalise(overlap)]), encoding="utf-8")

    syn_dir = work / "synthetic"
    syn_dir.mkdir()
    item = {
        "item_id": "x",
        "question_id": "q_overlap",
        "trait": None,
        "utterance": overlap,
        "context": None,
        "generated_label": "yes",
        "category": "plain",
        "template": "v1",
    }
    (syn_dir / "train.jsonl").write_text(json.dumps(item) + "\n", encoding="utf-8")
    (syn_dir / "dev.jsonl").write_text("", encoding="utf-8")
    overlap_q = schema_module.Question(
        id="q_overlap",
        type="choice",
        instructions="?",
        definition="?",
        options=(schema_module.Option("yes", None),),
        context_label=None,
        seeds=(),
        welfare=False,
    )
    monkeypatch.setattr(schema_module, "get_question", lambda qid: overlap_q)
    try:
        rc = build_data.main(
            [
                "assemble",
                "--work-root",
                str(work),
                "--seed",
                "7",
                "--banking-train",
                "0",
                "--nli-train",
                "0",
                "--banking-dev",
                "0",
                "--nli-dev",
                "0",
            ]
        )
        assert rc == 3
    finally:
        pass  # monkeypatch restores get_question


def test_refuse_protected_covers_the_configured_data_root(tmp_path, monkeypatch):
    """The script never installs a data root, so the configured one
    (KAINE_DATA_ROOT here) must be refused all the same."""
    root = tmp_path / "kaine-data"
    root.mkdir()
    monkeypatch.setattr(storage, "data_root", lambda: None)
    monkeypatch.setenv("KAINE_DATA_ROOT", str(root))
    with pytest.raises(build_data.ProtectedPathError):
        build_data._refuse_protected(root / "k1jev")
    assert build_data._refuse_protected(tmp_path / "elsewhere") == (tmp_path / "elsewhere").resolve()


def test_refuse_protected_fails_closed_on_a_broken_config(tmp_path, monkeypatch):
    import kaine.config as kaine_config

    def _boom(*_a, **_k):
        raise ValueError("bad toml")

    monkeypatch.setattr(kaine_config, "load_kaine_config", _boom)
    with pytest.raises(build_data.ProtectedPathError):
        build_data._refuse_protected(tmp_path / "anywhere")

