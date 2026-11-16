# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_audition_feeds as baf


def test_positive_record_structure_and_determinism(tmp_path):
    a = baf.build_record(seed=7, n_blocks=12, surprise_interval=4)
    b = baf.build_record(seed=7, n_blocks=12, surprise_interval=4)

    assert a == b
    assert a["feeding_version"] == "1.0"
    assert a["feed_family"] == "synthetic_seeded"
    assert a["seed"] == 7
    assert a["block_count"] == 12
    assert len(a["labels"]) == 12
    assert all(x in (0, 1) for x in a["labels"])
    assert len(a["batas"]) == 12
    assert all(isinstance(h, str) and len(h) == 64 for h in a["batas"])
    assert "spectral" in a["encoder_summary"]
    assert a["encoder_summary"]["spectral"]["embedding_dim"] > 0

    out1 = tmp_path / "r1.json"
    out2 = tmp_path / "r2.json"
    assert baf.main(["--seed", "7", "--blocks", "12", "--surprise-interval", "4", "--out", str(out1)]) == 0
    assert baf.main(["--seed", "7", "--blocks", "12", "--surprise-interval", "4", "--out", str(out2)]) == 0
    h1 = hashlib.sha256(out1.read_bytes()).hexdigest()
    h2 = hashlib.sha256(out2.read_bytes()).hexdigest()
    assert h1 == h2

    blocks, labels, meta = baf.load_feed("synthetic", {"seed": 7, "surprise_interval": 4}, 12)
    assert len(blocks) == 12 == len(labels)
    assert meta["block_count"] == 12
