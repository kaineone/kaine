# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI for building K1-Jev training data."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any

import kaine.storage as storage
from kaine.decision import render, schema

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[1]


def _load_module(name: str, rel_path: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        name, _SCRIPT_DIR / rel_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sources = _load_module("k1jev_sources", "sources.py")
synth = _load_module("k1jev_synth", "synth.py")


class ProtectedPathError(Exception):
    """A path is under the protected data root or repo state directory."""


def _main_checkout_root() -> Path:
    """The main checkout (the parent of git's common dir); the repo root when
    git cannot say."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return _REPO_ROOT
    common = Path(out)
    if not common.is_absolute():
        common = (_REPO_ROOT / common).resolve()
    return common.parent


def _protected_roots() -> list[Path]:
    """Every location that may hold entity data: the installed data root, the
    configured one (``KAINE_DATA_ROOT`` or ``[storage].data_root``), and the
    repository's ``state/``. This script never installs a data root itself, so
    the configured root is resolved here rather than trusted to be installed."""
    main_root = _main_checkout_root()
    roots: list[Path] = [_REPO_ROOT / "state", main_root / "state"]
    installed = storage.data_root()
    if installed is not None:
        roots.append(Path(installed).resolve())
    try:
        from kaine.config import load_kaine_config

        # The live operator config sits in the main checkout, not in a
        # worktree, and the loader's default paths are relative to the cwd.
        configured = storage.configured_data_root(
            load_kaine_config(
                main_root / "config" / "kaine.toml",
                main_root / "config" / "kaine.operator.toml",
            )
        )
    except Exception as exc:  # a broken config must not open the guard
        raise ProtectedPathError(
            f"cannot read the KAINE config to find the data root: {exc}"
        ) from exc
    if configured is not None:
        roots.append(configured)
    return roots


def _refuse_protected(path: str | os.PathLike[str]) -> Path:
    """Resolve *path* and raise if it lies under any protected location."""
    p = Path(path).expanduser().resolve()
    for root in _protected_roots():
        try:
            p.relative_to(root.resolve())
        except ValueError:
            continue
        raise ProtectedPathError(f"refusing protected path under {root}: {p}")
    return p


def _default_labels_path() -> Path:
    """Default gold items path, mirroring label_server logic."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        git_common = Path(out.stdout.strip())
        if not git_common.is_absolute():
            git_common = (_REPO_ROOT / git_common).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_common = (_REPO_ROOT / ".git").resolve()
    # The gold ITEMS file. The labelling page keeps the operator's labels in
    # labels.jsonl beside it; the two must never be the same file.
    return git_common / "kaine-tools" / "k1jev" / "gold" / "items.jsonl"


def _normalise(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text.casefold().strip())


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    _atomic_write(path, text)


def _atomic_write_json(path: Path, obj: Any) -> None:
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _schema_seed_norms() -> set[str]:
    norms: set[str] = set()
    for q in schema.QUESTIONS:
        for seed in q.seeds:
            norms.add(_normalise(seed.utterance))
    return norms


def _load_norms(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _stats_serializable(obj: Any) -> Any:
    if isinstance(obj, Counter):
        return dict(obj)
    if isinstance(obj, dict):
        return {k: _stats_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stats_serializable(v) for v in obj]
    return obj


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _all_question_ids() -> list[str]:
    return [q.id for q in schema.QUESTIONS]


def _parse_shard(value: str) -> tuple[int, int]:
    """Parse ``K/N`` with ``1 <= K <= N``."""
    if value.count("/") != 1:
        raise ValueError("expected K/N")
    k_str, n_str = value.split("/")
    if not k_str or not n_str:
        raise ValueError("expected K/N")
    try:
        k = int(k_str)
        n = int(n_str)
    except ValueError as exc:
        raise ValueError(f"non-integer shard component: {exc}") from exc
    if n < 1:
        raise ValueError("N must be at least 1")
    if k < 1 or k > n:
        raise ValueError("K must satisfy 1 <= K <= N")
    return k, n


def _merge_shard_stats(shard_stats_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum the numeric ``stats`` objects from shard stats files and keep metadata."""
    first = shard_stats_list[0]
    merged_stats: dict[str, Any] = {
        "total_requested": 0,
        "total_parsed": 0,
        "total_accepted": 0,
        "style_drops": 0,
        "duplicate_drops": 0,
        "seed_drops": 0,
        "other_split_drops": 0,
        "label_drops": 0,
        "label_drop_answers": {},
        "per_question_accepted": {},
    }
    for shard_stats in shard_stats_list:
        stats = shard_stats.get("stats", {})
        for key in (
            "total_requested",
            "total_parsed",
            "total_accepted",
            "style_drops",
            "duplicate_drops",
            "seed_drops",
            "other_split_drops",
            "label_drops",
        ):
            merged_stats[key] += stats.get(key, 0)

        for qid, styles in stats.get("label_drop_answers", {}).items():
            merged_styles = merged_stats["label_drop_answers"].setdefault(qid, {})
            for style, answers in styles.items():
                merged_answers = merged_styles.setdefault(style, {})
                for answer, count in answers.items():
                    merged_answers[answer] = merged_answers.get(answer, 0) + count

        for qid, styles in stats.get("per_question_accepted", {}).items():
            merged_styles = merged_stats["per_question_accepted"].setdefault(qid, {})
            for style, count in styles.items():
                merged_styles[style] = merged_styles.get(style, 0) + count

    return {
        "seed": first.get("seed"),
        "per_question": first.get("per_question"),
        "near_miss_share": first.get("near_miss_share"),
        "split": first.get("split"),
        "plan": first.get("plan"),
        "stats": merged_stats,
        "shards": shard_stats_list,
    }


def _cmd_fetch(args: argparse.Namespace) -> int:
    if not args.work_root:
        print("fetch requires --work-root", file=sys.stderr)
        return 2
    work_root = _refuse_protected(args.work_root)
    work_root.mkdir(parents=True, mode=0o700, exist_ok=True)

    names = args.names or list(sources.PINNED.keys())
    for name in names:
        _, _, size, licence = sources.PINNED[name]
        size_str = str(size) if size is not None else "unknown"
        print(f"{name}\tlicence={licence}\tsize={size_str}")

    if not args.yes:
        print("re-run with --yes to download", file=sys.stderr)
        return 2

    sources.fetch(work_root, names)
    return 0


def _cmd_gold(args: argparse.Namespace) -> int:
    work_root: Path | None = None
    if args.work_root:
        work_root = _refuse_protected(args.work_root)
        work_root.mkdir(parents=True, mode=0o700, exist_ok=True)

    out_items = _refuse_protected(args.out_items or _default_labels_path())
    out_items.parent.mkdir(parents=True, mode=0o700, exist_ok=True)

    api_key = os.environ.get(args.api_key_env)
    endpoint = synth.Endpoint(args.chat_url, api_key)

    if args.top_up:
        if not out_items.exists():
            print(f"top-up requires an existing items file: {out_items}", file=sys.stderr)
            return 2

        original_stats_path = _refuse_protected(out_items.with_suffix(".stats.json"))
        if not original_stats_path.exists():
            print(f"top-up requires original stats file: {original_stats_path}", file=sys.stderr)
            return 2
        with original_stats_path.open(encoding="utf-8") as f:
            original_stats = json.load(f)

        original_seed = original_stats.get("seed")
        if original_seed is None:
            print("top-up: original stats file has no seed", file=sys.stderr)
            return 2

        seed = args.seed if args.seed is not None else original_seed + 1
        if seed == original_seed:
            print(
                f"top-up seed {seed} must differ from original seed {original_seed}",
                file=sys.stderr,
            )
            return 2

        original_per_question = original_stats.get("per_question")
        if original_per_question is None:
            print("top-up: original stats file has no per_question", file=sys.stderr)
            return 2
        if args.per_question is not None and args.per_question != original_per_question:
            print(
                f"top-up: --per-question {args.per_question} differs from original {original_per_question}",
                file=sys.stderr,
            )
            return 2
        per_question = original_per_question

        existing_items: list[dict[str, Any]] = []
        existing_ids: set[str] = set()
        existing_norms: set[str] = set()
        with out_items.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                existing_items.append(item)
                existing_ids.add(item["item_id"])
                existing_norms.add(_normalise(item["utterance"]))

        # The quota is fixed by the original plan; the top-up seed is only for
        # generation.
        rng = random.Random(original_seed)
        question_ids = _all_question_ids()
        jobs = synth.plan_top_up(
            existing_items, question_ids, per_question, rng, near_miss_share=0.5
        )
        if not jobs:
            print("every cell is already at quota; nothing to top up", file=sys.stderr)
            return 0

        items, stats = synth.run_jobs(
            endpoint,
            jobs,
            master_seed=seed,
            existing_norms=existing_norms | _schema_seed_norms(),
            label_check=True,
            concurrency=4,
        )

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "Z"

        if not items:
            print("top-up: no new items accepted", file=sys.stderr)
            topup_stats = {
                "seed": seed,
                "original_seed": original_seed,
                "per_question": per_question,
                "original_per_question": per_question,
                "plan": [dataclasses.asdict(j) for j in jobs],
                "stats": _stats_serializable(stats),
                "added": {},
            }
            topup_stats_path = _refuse_protected(
                out_items.with_suffix(f".topup-{timestamp}.stats.json")
            )
            _atomic_write_json(topup_stats_path, topup_stats)
            return 0

        new_ids = {i["item_id"] for i in items}
        if new_ids & existing_ids:
            print("refusing top-up: new item_id collides with an existing item_id", file=sys.stderr)
            return 3

        backup_path = _refuse_protected(
            out_items.with_name(out_items.name + f".pre-topup-{timestamp}")
        )
        shutil.copy2(out_items, backup_path)
        backup_path.chmod(0o600)

        _atomic_write_jsonl(out_items, existing_items + items)

        # Nested by question, then label: JSON object keys must be strings.
        added: dict[str, dict[str, int]] = {}
        for i in items:
            per_q = added.setdefault(i["question_id"], {})
            per_q[i["generated_label"]] = per_q.get(i["generated_label"], 0) + 1
        topup_stats = {
            "seed": seed,
            "original_seed": original_seed,
            "per_question": per_question,
            "original_per_question": per_question,
            "plan": [dataclasses.asdict(j) for j in jobs],
            "stats": _stats_serializable(stats),
            "added": added,
        }
        topup_stats_path = _refuse_protected(
            out_items.with_suffix(f".topup-{timestamp}.stats.json")
        )
        _atomic_write_json(topup_stats_path, topup_stats)

        if work_root is not None:
            norms_path = work_root / "gold_norms.json"
            all_norms: set[str] = set()
            if norms_path.exists():
                all_norms.update(_load_norms(norms_path))
            all_norms.update(_normalise(i["utterance"]) for i in items)
            _atomic_write_json(norms_path, sorted(all_norms))

        return 0

    # Non-top-up (original behaviour).
    if out_items.exists():
        print(f"refusing to overwrite existing items: {out_items}", file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else 20261005
    rng = random.Random(seed)
    question_ids = _all_question_ids()
    existing_norms = _schema_seed_norms()

    per_question = args.per_question if args.per_question is not None else 30
    jobs = synth.plan(question_ids, per_question, rng, near_miss_share=0.5)
    items, stats = synth.run_jobs(
        endpoint,
        jobs,
        master_seed=seed,
        existing_norms=existing_norms,
        label_check=True,
        concurrency=4,
    )

    _atomic_write_jsonl(out_items, items)
    stats_out = {
        "plan": [dataclasses.asdict(j) for j in jobs],
        "stats": _stats_serializable(stats),
        "seed": seed,
        "per_question": per_question,
    }
    _atomic_write_json(out_items.with_suffix(".stats.json"), stats_out)

    if work_root is not None:
        norms = sorted({_normalise(i["utterance"]) for i in items})
        _atomic_write_json(work_root / "gold_norms.json", norms)

    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    if not args.work_root:
        print("generate requires --work-root", file=sys.stderr)
        return 2
    work_root = _refuse_protected(args.work_root)
    work_root.mkdir(parents=True, mode=0o700, exist_ok=True)

    try:
        shard_k, shard_n = _parse_shard(args.shard)
    except ValueError as exc:
        print(f"invalid --shard {args.shard!r}: {exc}", file=sys.stderr)
        return 2

    if args.concurrency < 1:
        print("--concurrency must be at least 1", file=sys.stderr)
        return 2

    gold_norms_path = work_root / "gold_norms.json"
    if not args.no_gold and not gold_norms_path.exists():
        print("missing gold norms; run gold first or use --no-gold", file=sys.stderr)
        return 2

    existing: set[str] = set()
    if not args.no_gold:
        existing.update(_load_norms(gold_norms_path))

    for split in ("train", "dev"):
        norms_path = work_root / "synthetic" / f"{split}_norms.json"
        if norms_path.exists():
            existing.update(_load_norms(norms_path))

    out_dir = work_root / "synthetic"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

    # Earlier shards of the same split must already exist so deduplication is
    # never partial.
    for k in range(1, shard_k):
        shard_norms_path = out_dir / f"{args.split}.shard-{k}-of-{shard_n}_norms.json"
        if not shard_norms_path.exists():
            print(
                f"missing earlier shard norms: {shard_norms_path}; "
                f"run shards in order 1..{shard_k - 1} first",
                file=sys.stderr,
            )
            return 3
        existing.update(_load_norms(shard_norms_path))

    rng = random.Random(args.seed)
    question_ids = _all_question_ids()
    full_jobs = synth.plan(
        question_ids, args.per_question, rng, near_miss_share=args.near_miss_share
    )
    job_indices = [i for i, _ in enumerate(full_jobs) if i % shard_n == shard_k - 1]
    shard_jobs = [full_jobs[i] for i in job_indices]

    if shard_n == 1:
        jsonl_path = out_dir / f"{args.split}.jsonl"
        stats_path = out_dir / f"{args.split}.stats.json"
        norms_path = out_dir / f"{args.split}_norms.json"
    else:
        jsonl_path = out_dir / f"{args.split}.shard-{shard_k}-of-{shard_n}.jsonl"
        stats_path = out_dir / f"{args.split}.shard-{shard_k}-of-{shard_n}.stats.json"
        norms_path = out_dir / f"{args.split}.shard-{shard_k}-of-{shard_n}_norms.json"

        if jsonl_path.exists():
            print(f"refusing to overwrite existing shard file: {jsonl_path}", file=sys.stderr)
            return 2

    api_key = os.environ.get(args.api_key_env)
    endpoint = synth.Endpoint(args.chat_url, api_key)
    items, stats = synth.run_jobs(
        endpoint,
        shard_jobs,
        master_seed=args.seed,
        existing_norms=existing,
        label_check=True,
        concurrency=args.concurrency,
        job_indices=job_indices,
    )

    _atomic_write_jsonl(jsonl_path, items)
    stats_out = {
        "plan": [dataclasses.asdict(j) for j in full_jobs],
        "stats": _stats_serializable(stats),
        "seed": args.seed,
        "per_question": args.per_question,
        "near_miss_share": args.near_miss_share,
        "split": args.split,
    }
    if shard_n > 1:
        stats_out["shard"] = shard_k
        stats_out["of"] = shard_n
        stats_out["job_indices"] = job_indices
        stats_out["job_count"] = len(job_indices)
    _atomic_write_json(stats_path, stats_out)
    _atomic_write_json(norms_path, sorted({_normalise(i["utterance"]) for i in items}))
    return 0


def _cmd_merge_shards(args: argparse.Namespace) -> int:
    if not args.work_root:
        print("merge-shards requires --work-root", file=sys.stderr)
        return 2
    work_root = _refuse_protected(args.work_root)
    out_dir = work_root / "synthetic"

    shard_files: list[Path] = []
    shard_stats_files: list[Path] = []
    for k in range(1, args.of_n + 1):
        jsonl_path = out_dir / f"{args.split}.shard-{k}-of-{args.of_n}.jsonl"
        stats_path = out_dir / f"{args.split}.shard-{k}-of-{args.of_n}.stats.json"
        if not jsonl_path.exists():
            print(f"missing shard file: {jsonl_path}", file=sys.stderr)
            return 3
        if not stats_path.exists():
            print(f"missing shard stats file: {stats_path}", file=sys.stderr)
            return 3
        shard_files.append(jsonl_path)
        shard_stats_files.append(stats_path)

    merged_jsonl_path = out_dir / f"{args.split}.jsonl"
    if merged_jsonl_path.exists():
        print(f"refusing to overwrite existing {merged_jsonl_path}", file=sys.stderr)
        return 2

    all_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_norms: set[str] = set()
    for jsonl_path in shard_files:
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                item_id = item["item_id"]
                norm = _normalise(item["utterance"])
                if item_id in seen_ids:
                    print(f"duplicate item_id across shards: {item_id}", file=sys.stderr)
                    return 3
                if norm in seen_norms:
                    print(
                        f"duplicate normalised utterance across shards: {norm[:80]!r}",
                        file=sys.stderr,
                    )
                    return 3
                seen_ids.add(item_id)
                seen_norms.add(norm)
                all_items.append(item)

    shard_stats_list = []
    for stats_path in shard_stats_files:
        with stats_path.open(encoding="utf-8") as f:
            shard_stats_list.append(json.load(f))

    merged_stats = _merge_shard_stats(shard_stats_list)

    _atomic_write_jsonl(merged_jsonl_path, all_items)
    _atomic_write_json(out_dir / f"{args.split}_norms.json", sorted(seen_norms))
    _atomic_write_json(out_dir / f"{args.split}.stats.json", merged_stats)
    return 0


def _cmd_assemble(args: argparse.Namespace) -> int:
    if not args.work_root:
        print("assemble requires --work-root", file=sys.stderr)
        return 2
    work_root = _refuse_protected(args.work_root)
    work_root.mkdir(parents=True, mode=0o700, exist_ok=True)

    # Load synthetic splits
    synthetic_dir = work_root / "synthetic"
    synthetic: dict[str, list[dict[str, Any]]] = {"train": [], "dev": []}
    for split in ("train", "dev"):
        path = synthetic_dir / f"{split}.jsonl"
        if not path.exists():
            # The synthetic questions are the point of K1-Jev; never assemble
            # a training set without them.
            print(f"missing {path}; run generate --split {split} first", file=sys.stderr)
            return 3
        with path.open(encoding="utf-8") as f:
            synthetic[split] = [json.loads(line) for line in f if line.strip()]

    # Gold-norm overlap check. It cannot be skipped by a missing file: without
    # the gold norms the disjointness of train/dev from gold is unknown.
    gold_norms: set[str] = set()
    gold_norms_path = work_root / "gold_norms.json"
    if not args.no_gold:
        if not gold_norms_path.exists():
            print(
                f"missing {gold_norms_path}; run gold with --work-root first "
                "(or pass --no-gold for a build with no gold set)",
                file=sys.stderr,
            )
            return 3
        gold_norms.update(_load_norms(gold_norms_path))

    for item in synthetic["train"] + synthetic["dev"]:
        if _normalise(item["utterance"]) in gold_norms:
            print("synthetic utterance overlaps gold norm", file=sys.stderr)
            return 3

    rng = random.Random(args.seed)

    # Public datasets
    banking_train = sources.banking77_examples(
        work_root / "cache" / "banking77" / "train.csv",
        random.Random(rng.randint(0, 2**31)),
        n=args.banking_train,
    )
    banking_dev = sources.banking77_examples(
        work_root / "cache" / "banking77" / "test.csv",
        random.Random(rng.randint(0, 2**31)),
        n=args.banking_dev,
    )
    nli_train, nli_train_counts = sources.multinli_examples(
        work_root / "cache" / "multinli" / "train.parquet",
        random.Random(rng.randint(0, 2**31)),
        n=args.nli_train,
    )
    nli_dev, nli_dev_counts = sources.multinli_examples(
        work_root / "cache" / "multinli" / "validation_matched.parquet",
        random.Random(rng.randint(0, 2**31)),
        n=args.nli_dev,
    )

    for counts in (nli_train_counts, nli_dev_counts):
        if counts.get("fiction", 0) > 0:
            print("fiction present in NLI data", file=sys.stderr)
            return 3

    def _to_question(options: list[list[Any]]) -> Any:
        return types.SimpleNamespace(
            id="unused",
            type="choice",
            instructions="unused",
            options=tuple(schema.Option(key=k, description=d) for k, d in options),
        )

    def _public_example(ex: dict[str, Any]) -> tuple[Any, str, str, str, str]:
        q = types.SimpleNamespace(
            id=ex["question_id"],
            type=ex["type"],
            instructions=ex["instructions"],
            options=tuple(schema.Option(key=k, description=d) for k, d in ex["options"]),
        )
        return (q, ex["state"], ex["answer"], ex["question_id"], ex["source"])

    train_examples: list[tuple[Any, str, str, str, str]] = []
    for item in synthetic["train"]:
        q = schema.get_question(item["question_id"])
        state = schema.state_text(item["utterance"], item["context"])
        train_examples.append((q, state, item["generated_label"], item["question_id"], "synthetic"))

    dev_examples: list[tuple[Any, str, str, str, str]] = []
    for item in synthetic["dev"]:
        q = schema.get_question(item["question_id"])
        state = schema.state_text(item["utterance"], item["context"])
        dev_examples.append((q, state, item["generated_label"], item["question_id"], "synthetic"))

    train_examples.extend(_public_example(e) for e in banking_train)
    train_examples.extend(_public_example(e) for e in nli_train)
    dev_examples.extend(_public_example(e) for e in banking_dev)
    dev_examples.extend(_public_example(e) for e in nli_dev)

    splits = {"train": train_examples, "dev": dev_examples}

    assembled_dir = work_root / "assembled"
    assembled_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

    manifest: dict[str, Any] = {
        "schema_version": schema.SCHEMA_VERSION,
        "schema_digest": schema.schema_digest(),
        "generator_model": args.model,
        "licences": {name: lic for name, (_, _, _, lic) in sources.PINNED.items()},
        "input_hashes": {},
        "output_hashes": {},
        "counts": {},
        "seeds": {"assemble": args.seed},
        "git_head": _git_head(),
        "nli_genre_counts": {"train": nli_train_counts, "dev": nli_dev_counts},
        "gold_excluded": not args.no_gold,
        "gold_norms_sha256": (
            _sha256_file(gold_norms_path) if not args.no_gold else None
        ),
    }

    for name in sources.PINNED:
        p = work_root / "cache" / name
        if p.exists():
            manifest["input_hashes"][name] = _sha256_file(p)

    for split, examples in splits.items():
        rng_split = random.Random(args.seed + (0 if split == "train" else 1))
        records: list[dict[str, Any]] = []
        per_source = Counter()
        per_question = Counter()
        per_answer = Counter()

        for idx, (q, state, answer_key, qid, src) in enumerate(examples):
            per_source[src] += 1
            per_question[qid] += 1
            per_answer[f"{qid}|{answer_key}"] += 1

            if q.type == "score":
                opts = q.options
            else:
                if rng_split.random() < 0.5:
                    opts = q.options
                else:
                    opts = list(q.options)
                    random.Random(args.seed + idx + (0 if split == "train" else 1_000_000)).shuffle(opts)

            prompt, answer_letter = render.training_example(q, state, answer_key, options=opts)
            records.append(
                {
                    "prompt": prompt,
                    "answer": answer_letter,
                    # The SFT loss is a softmax over the option letters, as
                    # /v1/systemone serves it, so training needs the count.
                    "n_options": len(opts),
                    "source": src,
                    "question_id": qid,
                }
            )

        _atomic_write_jsonl(assembled_dir / f"{split}.jsonl", records)
        manifest["output_hashes"][f"{split}.jsonl"] = _sha256_file(
            assembled_dir / f"{split}.jsonl"
        )
        manifest["counts"][split] = {
            "source": dict(per_source),
            "question": dict(per_question),
            "answer": dict(per_answer),
        }

    manifest["counts"]["total"] = {
        "train": len(splits["train"]),
        "dev": len(splits["dev"]),
    }

    _atomic_write_json(assembled_dir / "manifest.json", manifest)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Common options live on a parent parser shared by every subcommand, so
    # they are accepted after the subcommand name (``build_data.py gold
    # --work-root DIR``), which is how the docs and the tests write them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--work-root", type=str, default=None)
    common.add_argument("--chat-url", type=str, default="http://127.0.0.1:11450/v1")
    common.add_argument("--model", type=str, default="qwen3.5-9b-generator")
    common.add_argument("--api-key-env", type=str, default="K1JEV_GENERATOR_KEY")

    parser = argparse.ArgumentParser(description="K1-Jev data builder")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", parents=[common])
    fetch_p.add_argument("--names", nargs="*", choices=list(sources.PINNED.keys()))
    fetch_p.add_argument("--yes", action="store_true")

    gold_p = sub.add_parser("gold", parents=[common])
    gold_p.add_argument("--out-items", type=str, default=None)
    gold_p.add_argument("--per-question", type=int, default=None, help="default 30")
    gold_p.add_argument("--seed", type=int, default=None)
    gold_p.add_argument("--top-up", action="store_true")

    gen_p = sub.add_parser("generate", parents=[common])
    gen_p.add_argument("--split", choices=["train", "dev"], required=True)
    gen_p.add_argument("--per-question", type=int, required=True)
    gen_p.add_argument("--seed", type=int, required=True)
    gen_p.add_argument("--near-miss-share", type=float, default=0.5)
    gen_p.add_argument("--no-gold", action="store_true")
    gen_p.add_argument("--shard", type=str, default="1/1")
    gen_p.add_argument("--concurrency", type=int, default=4)

    merge_p = sub.add_parser("merge-shards", parents=[common])
    merge_p.add_argument("--split", choices=["train", "dev"], required=True)
    merge_p.add_argument("--of", type=int, required=True, dest="of_n")

    asm_p = sub.add_parser("assemble", parents=[common])
    asm_p.add_argument("--seed", type=int, default=20261005)
    asm_p.add_argument("--no-gold", action="store_true")
    asm_p.add_argument("--banking-train", type=int, default=10_000)
    asm_p.add_argument("--nli-train", type=int, default=15_000)
    asm_p.add_argument("--banking-dev", type=int, default=1_500)
    asm_p.add_argument("--nli-dev", type=int, default=2_000)

    args = parser.parse_args(argv)

    try:
        if args.command == "fetch":
            return _cmd_fetch(args)
        if args.command == "gold":
            return _cmd_gold(args)
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "merge-shards":
            return _cmd_merge_shards(args)
        if args.command == "assemble":
            return _cmd_assemble(args)
        print(f"unknown command: {args.command}", file=sys.stderr)
        return 2
    except ProtectedPathError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
