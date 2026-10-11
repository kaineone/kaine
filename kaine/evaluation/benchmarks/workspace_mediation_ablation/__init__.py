# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline development harness for the workspace-mediation test.

This package runs a reduced pair of real processors (Soma and Topos) against a
pooled control arm only. The workspace-on arm uses competitive selection; the
pooled arm admits every candidate weighted by its intensity. The measure is the
cross-module broadcast information gain, read from each processor's
``context_gain`` field on its report payload.

The harness is seeded and deterministic. It boots no entity and opens no
network connection. It is development tooling and does not test the thesis. The
language organ is not used, and its rendered output is not a measure.
"""
from __future__ import annotations
