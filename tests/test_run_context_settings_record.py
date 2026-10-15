# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from kaine.experiment.run_context import mint_run_context


def test_mint_run_context_records_settings_digest() -> None:
    ctx = mint_run_context(
        seed=1,
        started_at="2026-01-01T00:00:00Z",
        config={},
        model_ids={},
        version="x",
        settings_record_sha256="ab" * 32,
    )
    assert ctx.to_dict()["settings_record_sha256"] == "ab" * 32


def test_mint_run_context_omits_settings_digest_when_none() -> None:
    ctx = mint_run_context(
        seed=1,
        started_at="2026-01-01T00:00:00Z",
        config={},
        model_ids={},
        version="x",
    )
    assert ctx.to_dict().get("settings_record_sha256") is None
