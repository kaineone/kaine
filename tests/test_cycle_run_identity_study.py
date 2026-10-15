# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from kaine.config import resolve_study_name


def test_resolve_study_name_reads_the_environment(monkeypatch):
    monkeypatch.setenv("KAINE_STUDY", "workspace_mediation_pooled")
    assert resolve_study_name() == "workspace_mediation_pooled"

    monkeypatch.delenv("KAINE_STUDY", raising=False)
    assert resolve_study_name() is None
