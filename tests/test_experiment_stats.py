# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
import random

import pytest

from kaine.experiment.stats import mean, percentile, std

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def test_empty_and_trivial_are_zero():
    assert mean([]) == 0.0
    assert std([1.0]) == 0.0
    assert percentile([], 50) == 0.0


def test_population_std():
    assert std([1, 2, 3, 4]) == math.sqrt(1.25)


@pytest.mark.skipif(np is None, reason="numpy not available")
def test_percentile_matches_numpy():
    rng = random.Random(20261003)
    for _ in range(20):
        values = [rng.uniform(-100.0, 100.0) for _ in range(rng.randint(1, 50))]
        for pct in (0, 25, 50, 90, 95, 99, 100):
            expected = np.percentile(values, pct)
            assert percentile(values, pct) == pytest.approx(expected, abs=1e-12)


def test_single_value_percentile():
    assert percentile([5.0], 95) == 5.0
