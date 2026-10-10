# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Test support: intent records that carry a verified system prompt.

Training refuses a pair whose system prompt cannot be read back and verified
(voice-development D14), so tests that drive the trainer write the persona into
the store next to the intent log and stamp each record with its digest.
"""
from __future__ import annotations

from pathlib import Path

from kaine.persistence.system_prompts import store_dir_for, write_system_prompt

TEST_PERSONA = "I am a test persona."


def with_verified_system(log_path: Path, records: list[dict]) -> list[dict]:
    """Write the test persona to the store and stamp every record with it."""
    digest = write_system_prompt(store_dir_for(Path(log_path)), TEST_PERSONA)
    return [{**r, "system_digest": digest} for r in records]
