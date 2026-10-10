# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for outcome_category."""
from __future__ import annotations

import pytest

from kaine.evaluation.observers.voice_alignment_divergence_observer import (
    outcome_category,
)


@pytest.mark.parametrize(
    "accepted, reason, samples_used, expected",
    [
        (True, "abliteration veto passed", 3, "accepted"),
        (
            False,
            "trainer raised: FileNotFoundError: /home/x/y",
            3,
            "failed",
        ),
        (
            False,
            "capability regression: loss 0.2 > 0.05",
            4,
            "vetoed_capability",
        ),
        (
            False,
            "abliteration veto: deflection on probe 2",
            4,
            "vetoed_abliteration",
        ),
        (
            False,
            "no usable DPO pairs in intent-expression log",
            0,
            "no_pairs",
        ),
    ],
)
def test_outcome_category(accepted, reason, samples_used, expected):
    assert outcome_category(accepted, reason, samples_used) == expected
