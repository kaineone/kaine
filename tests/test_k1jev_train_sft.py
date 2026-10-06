# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev SFT trainer."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_STATE_DIR = (REPO_ROOT / "state").resolve()

_TRAIN_SFT_SPEC = importlib.util.spec_from_file_location(
    "k1jev_train_sft", REPO_ROOT / "scripts" / "k1jev" / "train_sft.py"
)
train_sft = importlib.util.module_from_spec(_TRAIN_SFT_SPEC)
sys.modules["k1jev_train_sft"] = train_sft
_TRAIN_SFT_SPEC.loader.exec_module(train_sft)


def test_importing_module_does_not_load_heavy_packages():
    before = set(sys.modules.keys())
    spec = importlib.util.spec_from_file_location(
        "k1jev_train_sft_fresh", REPO_ROOT / "scripts" / "k1jev" / "train_sft.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["k1jev_train_sft_fresh"] = mod
    spec.loader.exec_module(mod)
    after = set(sys.modules.keys())
    added = after - before
    assert not any(pkg in name for name in added for pkg in ("torch", "unsloth", "transformers", "peft"))


def test_entity_running_detects_docker_container():
    def runner(argv):
        return "kaine-cycle\n"

    reason = train_sft.entity_running(
        docker_argv_runner=runner,
        proc_root=Path("/nonexistent"),
        self_pid=1,
    )
    assert reason is not None
    assert "kaine-cycle" in reason


def test_entity_running_detects_proc_cycle(tmp_path):
    pid_dir = tmp_path / "1234"
    pid_dir.mkdir()
    (pid_dir / "cmdline").write_bytes(b"python\x00-m\x00kaine.cycle\x00")

    reason = train_sft.entity_running(
        docker_argv_runner=lambda a: "",
        proc_root=tmp_path,
        self_pid=9999,
    )
    assert reason is not None
    assert "kaine.cycle" in reason


def test_entity_running_ignores_self_pid(tmp_path):
    pid_dir = tmp_path / "1234"
    pid_dir.mkdir()
    (pid_dir / "cmdline").write_bytes(b"python\x00-m\x00kaine.cycle\x00")

    reason = train_sft.entity_running(
        docker_argv_runner=lambda a: "",
        proc_root=tmp_path,
        self_pid=1234,
    )
    assert reason is None


def test_entity_running_missing_docker_still_checks_proc(tmp_path):
    def runner(argv):
        raise FileNotFoundError("docker not found")

    pid_dir = tmp_path / "42"
    pid_dir.mkdir()
    (pid_dir / "cmdline").write_bytes(b"python\x00-m\x00kaine.cycle\x00")

    reason = train_sft.entity_running(
        docker_argv_runner=runner,
        proc_root=tmp_path,
        self_pid=1,
    )
    assert reason is not None
    assert "kaine.cycle" in reason


def test_entity_running_none_for_unrelated_processes(tmp_path):
    pid_dir = tmp_path / "100"
    pid_dir.mkdir()
    (pid_dir / "cmdline").write_bytes(b"python\x00other.py\x00")

    reason = train_sft.entity_running(
        docker_argv_runner=lambda a: "",
        proc_root=tmp_path,
        self_pid=999,
    )
    assert reason is None


def test_main_exits_three_when_entity_running(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(train_sft, "entity_running", lambda **kwargs: "entity detected")
    monkeypatch.setattr(
        sys,
        "argv",
        ["train_sft.py", "--base", "base", "--train", "train.jsonl", "--dev", "dev.jsonl", "--out", str(out)],
    )
    with pytest.raises(SystemExit) as exc_info:
        train_sft.main()
    assert exc_info.value.code == 3
    assert not out.exists()


def test_refuse_out_path_under_state():
    with pytest.raises(ValueError):
        train_sft.refuse_out_path(_STATE_DIR / "run")


def test_refuse_out_path_accepts_tmp(tmp_path):
    chosen = tmp_path / "run"
    assert train_sft.refuse_out_path(chosen) == chosen.resolve()


def test_load_examples_valid(tmp_path):
    path = tmp_path / "data.jsonl"
    records = [
        {"prompt": "p1", "answer": "A", "n_options": 4, "source": "s", "question_id": "1"},
        {"prompt": "p2", "answer": "z", "n_options": 52, "source": "s", "question_id": "2"},
    ]
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    loaded = train_sft.load_examples(path)
    assert len(loaded) == 2
    assert loaded[0]["answer"] == "A"


def test_load_examples_answer_beyond_n_options(tmp_path):
    path = tmp_path / "data.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"prompt": "p", "answer": "D", "n_options": 3, "source": "s", "question_id": "1"}) + "\n")
    with pytest.raises(ValueError) as exc_info:
        train_sft.load_examples(path)
    assert "line 1" in str(exc_info.value)


def test_load_examples_two_letter_answer(tmp_path):
    path = tmp_path / "data.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"prompt": "p", "answer": "AB", "n_options": 4, "source": "s", "question_id": "1"}) + "\n")
    with pytest.raises(ValueError) as exc_info:
        train_sft.load_examples(path)
    assert "line 1" in str(exc_info.value)


def test_load_examples_missing_key(tmp_path):
    path = tmp_path / "data.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"prompt": "p", "answer": "A", "n_options": 4, "source": "s"}) + "\n")
    with pytest.raises(ValueError) as exc_info:
        train_sft.load_examples(path)
    assert "line 1" in str(exc_info.value)


def test_bucket_batches_coverage():
    lengths = [5, 10, 15, 5, 10, 15]
    batches = train_sft.bucket_batches(lengths, 2, seed=123)
    flat = [idx for batch in batches for idx in batch]
    assert sorted(flat) == list(range(6))
    assert len(batches) == 3
    for batch in batches[:-1]:
        assert len(batch) == 2
    assert len(batches[-1]) == 2


def test_bucket_batches_deterministic_and_seed_sensitive():
    lengths = [5, 10, 15, 5, 10, 15]
    a = train_sft.bucket_batches(lengths, 2, seed=7)
    b = train_sft.bucket_batches(lengths, 2, seed=7)
    c = train_sft.bucket_batches(lengths, 2, seed=42)
    assert a == b
    assert a != c


def test_warmup_steps():
    assert train_sft.warmup_steps(1000, 0.03) == 30
    assert train_sft.warmup_steps(10, 0.03) == 1


def test_option_loss_favored_vs_uniform():
    pytest.importorskip("torch")
    import torch

    n = 4
    uniform = torch.zeros(2, n)
    favored = torch.zeros(2, n)
    favored[0, 0] = 10.0
    favored[1, 2] = 10.0
    target = torch.tensor([0, 2])

    loss_uniform = train_sft.option_loss(uniform, target)
    loss_favored = train_sft.option_loss(favored, target)

    assert loss_favored.item() < loss_uniform.item()


def test_option_loss_uniform_is_log_n():
    pytest.importorskip("torch")
    import torch

    for n in (2, 10, 52):
        logits = torch.zeros(1, n)
        loss = train_sft.option_loss(logits, torch.tensor([0]))
        assert abs(loss.item() - math.log(n)) < 1e-5


def test_left_pad_batch_pads_to_the_batch_maximum_only():
    ids, mask = train_sft.left_pad_batch([[5, 6, 7], [9]], pad_id=0)
    assert ids == [[5, 6, 7], [0, 0, 9]]
    assert mask == [[1, 1, 1], [0, 0, 1]]
    assert all(row[-1] != 0 for row in ids)  # last real token at -1


def test_entity_running_fails_closed_when_docker_errors(tmp_path):
    import subprocess

    def _timeout(_argv):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=30)

    proc = tmp_path / "proc"
    proc.mkdir()
    reason = train_sft.entity_running(docker_argv_runner=_timeout, proc_root=proc, self_pid=1)
    assert reason is not None and "cannot check" in reason


def test_targets_name_the_real_qwen35_projections():
    # transformers v5 Qwen3.5: attention, MLP and Gated DeltaNet projections.
    for name in ("q_proj", "o_proj", "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_b", "in_proj_a", "out_proj"):
        assert name in train_sft.TARGETS
    assert not any(t in train_sft.TARGETS for t in ("qkv", "proj", "linear_fc1", "linear_fc2"))


def test_entity_running_fails_closed_on_docker_nonzero_exit(tmp_path, monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(train_sft.subprocess, "run", lambda *a, **k: _Proc())
    proc = tmp_path / "proc"
    proc.mkdir()
    reason = train_sft.entity_running(proc_root=proc, self_pid=1)
    assert reason is not None and "cannot check" in reason


def test_bucket_batches_keep_similar_lengths_together():
    lengths = [10] * 8 + [500] * 8
    batches = train_sft.bucket_batches(lengths, batch=8, seed=3)
    for b in batches:
        assert len({lengths[i] for i in b}) == 1


def test_refuse_out_path_rejects_anywhere_in_the_repository(tmp_path):
    repo = Path(train_sft.__file__).resolve().parents[2]
    with pytest.raises(ValueError):
        train_sft.refuse_out_path(repo / ".git" / "kaine-tools" / "k1jev-out")
    assert train_sft.refuse_out_path(tmp_path / "out") == (tmp_path / "out").resolve()


def test_read_data_manifest_requires_the_schema_fields(tmp_path):
    train = tmp_path / "train.jsonl"
    train.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        train_sft.read_data_manifest(train)
    (tmp_path / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        train_sft.read_data_manifest(train)
    (tmp_path / "manifest.json").write_text('{"schema_version": 1, "schema_digest": "abc"}', encoding="utf-8")
    assert train_sft.read_data_manifest(train)["schema_digest"] == "abc"



def test_checkpoint_records_the_torch_rng_state(tmp_path):
    torch = pytest.importorskip("torch")

    class _Model:
        def save_pretrained(self, path):
            Path(path, "adapter_model.safetensors").write_bytes(b"")

    param = torch.nn.Parameter(torch.zeros(2))
    optimizer = torch.optim.AdamW([param], lr=1e-3)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1.0)
    torch.manual_seed(1234)
    expected = torch.get_rng_state()

    cp_dir = train_sft._save_checkpoint(tmp_path, 7, _Model(), optimizer, scheduler, 99, 10)

    state = torch.load(cp_dir / "trainer_state.pt", weights_only=False)
    assert state["step"] == 7
    assert torch.equal(state["rng_state"], expected)


def test_check_prompt_lengths_accepts_up_to_max_len():
    assert train_sft.check_prompt_lengths("train", [1, 5, 8], 8) is None


def test_check_prompt_lengths_refuses_over_long():
    with pytest.raises(ValueError, match="train") as excinfo:
        train_sft.check_prompt_lengths("train", [3, 9, 4, 12], 8)
    msg = str(excinfo.value)
    assert "0 empty and 2 over-long" in msg
    assert "max_len=8, longest=12" in msg
    assert "[1, 3]" in msg


def test_check_prompt_lengths_refuses_empty():
    with pytest.raises(ValueError, match="empty") as excinfo:
        train_sft.check_prompt_lengths("dev", [0, 4], 8)
    msg = str(excinfo.value)
    assert msg.startswith("dev: found 1 empty and 0 over-long")
    assert "[0]" in msg


def test_load_examples_refuses_empty_prompt(tmp_path):
    line = (
        '{"prompt": "  ", "answer": "A", "n_options": 2, "source": "s", "question_id": "q"}\n'
    )
    path = tmp_path / "empty_prompt.jsonl"
    path.write_text(line)
    with pytest.raises(ValueError, match="prompt"):
        train_sft.load_examples(path)

    path.write_text(
        '{"prompt": 123, "answer": "A", "n_options": 2, "source": "s", "question_id": "q"}\n'
    )
    with pytest.raises(ValueError, match="prompt"):
        train_sft.load_examples(path)


def test_trainer_never_truncates():
    src = Path(train_sft.__file__).read_text()
    assert "truncation=True" not in src
    assert "truncation_side" not in src
