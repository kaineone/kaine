# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

organ_replay_spec = importlib.util.spec_from_file_location(
    "organ_replay", REPO_ROOT / "tools" / "maintainer" / "organ_replay.py"
)
organ_replay = importlib.util.module_from_spec(organ_replay_spec)
organ_replay_spec.loader.exec_module(organ_replay)

test_organ_replay_spec = importlib.util.spec_from_file_location(
    "test_organ_replay", REPO_ROOT / "tests" / "test_organ_replay.py"
)
test_organ_replay = importlib.util.module_from_spec(test_organ_replay_spec)
test_organ_replay_spec.loader.exec_module(test_organ_replay)


def test_score_rule_v6_waking_requests_do_not_enter_decision(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    non_waking_prompt = "## How I feel and what I notice\n- a\n\n## My thought\n"
    waking_prompt = (
        organ_replay.SITUATION_HEADING
        + "\nSomething is happening.\n\n## How I feel and what I notice\n- a\n\n## My thought\n"
    )

    results = []
    for i in range(8):
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5", True, True, False, non_waking_prompt)
        )
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5m", False, True, False, non_waking_prompt)
        )
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5e", True, True, False, non_waking_prompt)
        )
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5l", True, True, False, non_waking_prompt)
        )

    for i in range(8, 12):
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5", False, False, True, waking_prompt)
        )
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5m", True, False, True, waking_prompt)
        )
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5e", False, False, True, waking_prompt)
        )
        results.append(
            test_organ_replay._synthetic_v6_result(i, "V5l", False, False, True, waking_prompt)
        )

    path = tmp_path / "results.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        results=str(path),
        bootstrap=200,
        rule="v6",
    )
    organ_replay._score_cmd(args)
    out = capsys.readouterr().out
    assert "Waking requests do not enter the decision." in out
    assert "winner: V5m" in out
