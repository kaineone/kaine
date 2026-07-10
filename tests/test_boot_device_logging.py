# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""build_registry emits one line per pinned module."""
from __future__ import annotations

import pytest

from kaine.boot import build_registry

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_build_registry_logs_topos_device(caplog):
    async with SubsystemHarness() as h:
        with caplog.at_level("INFO"):
            registry = build_registry(
                h.bus,
                {
                    "modules": {"topos": True, "mnemos": True, "audition": True},
                    "topos": {
                        "encoder_backend": "dinov2",
                        "encoder_model_id": "facebook/dinov2-small",
                        "device": "cuda:1",
                        "change_alert_threshold": 0.5,
                        "baseline_salience": 0.2,
                        "alert_salience": 0.7,
                    },
                    "mnemos": {
                        "backend": "inmemory",
                        "collection_prefix": "mnemos_",
                        "short_term_capacity": 8,
                        "recall_top_k": 3,
                        "device": "cpu",
                    },
                    "audition": {
                        "speaches_url": "http://127.0.0.1:8000",
                        "stt_model": "x",
                        "emotion_model_id": "y",
                        "emotion_device": "cpu",
                        "request_timeout_s": 60.0,
                    },
                },
            )
        text = "\n".join(rec.message for rec in caplog.records)
        assert "device assignment: topos.encoder → cuda:1" in text
        assert "device assignment: mnemos.embedder → cpu" in text
        assert "device assignment: audition.emotion → cpu" in text
        assert "topos" in registry
