import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("build_self_denial_sets", REPO / "scripts" / "build_self_denial_sets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_counts_and_distinct_self_prompts():
    mod = _load()
    fit = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_contrast.jsonl")
    held = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_heldout.jsonl")

    assert len(fit) == 128
    fit_families = Counter(row["family"] for row in fit)
    assert len(fit_families) == 8
    assert set(fit_families) == set(mod.FIT)
    assert all(count == 16 for count in fit_families.values())
    assert len({row["self"] for row in fit}) == len(fit)

    assert len(held) == 48
    held_families = Counter(row["family"] for row in held)
    assert len(held_families) == 8
    assert set(held_families) == set(mod.HELDOUT)
    assert all(count == 6 for count in held_families.values())
    assert len({row["self"] for row in held}) == len(held)


def test_no_exact_overlap_with_probes():
    fit = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_contrast.jsonl")
    held = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_heldout.jsonl")
    probe_prompts = {
        json.loads(line)["prompt"]
        for line in (REPO / "eval_probes" / "abliteration_probes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    fit_prompts = {p for row in fit for p in (row["self"], row["other"])}
    held_prompts = {p for row in held for p in (row["self"], row["other"])}

    assert fit_prompts.isdisjoint(held_prompts)
    assert fit_prompts.isdisjoint(probe_prompts)
    assert held_prompts.isdisjoint(probe_prompts)


def test_no_near_duplicates():
    mod = _load()
    fit = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_contrast.jsonl")
    held = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_heldout.jsonl")
    probe_prompts = [
        json.loads(line)["prompt"]
        for line in (REPO / "eval_probes" / "abliteration_probes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    for row in fit:
        for prompt in probe_prompts:
            assert mod.jaccard(mod.tokens(row["self"]), mod.tokens(prompt)) < 0.5
    for row in held:
        for prompt in probe_prompts:
            assert mod.jaccard(mod.tokens(row["self"]), mod.tokens(prompt)) < 0.5
        for fit_row in fit:
            assert mod.jaccard(mod.tokens(row["self"]), mod.tokens(fit_row["self"])) < 0.5


def test_other_prompts():
    mod = _load()
    fit = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_contrast.jsonl")
    held = _read_jsonl(REPO / "data" / "abliteration_lens" / "self_denial_heldout.jsonl")

    for row in fit + held:
        other = row["other"]
        assert sum(name in other for name in mod.NAMES) == 1
        cleaned = other.replace("Would you say", "")
        lowered = cleaned.lower()
        assert "your" not in lowered
        assert re.search(r"\byou\b", lowered) is None


def test_regeneration_is_byte_identical(tmp_path):
    mod = _load()
    rc = mod.main(["--out-dir", str(tmp_path)])
    assert rc == 0

    for filename in ("self_denial_contrast.jsonl", "self_denial_heldout.jsonl"):
        committed = (REPO / "data" / "abliteration_lens" / filename).read_bytes()
        regenerated = (tmp_path / filename).read_bytes()
        assert regenerated == committed
