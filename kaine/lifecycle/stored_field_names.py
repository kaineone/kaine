# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Field names that stored data keeps after a Python field is renamed.

Digests and manifests written before a rename hash or name the old field names, so the
serialized form keeps them for good, whatever the Python field is now called. The rename
codemod excludes this file (EXCLUDED_GLOBS in kaine/legacy_names.py), so its literal names
never change.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

# Python field name -> the name in stage.json digests and feed descriptors.
STIMULUS_SOURCE_PARAMS: dict[str, str] = {
    "maturation_transition_seconds": "birth_transition_seconds",
}


def stimulus_source_params_record(params: object) -> dict[str, Any]:
    """``asdict(params)`` with each renamed field under the name stored data uses."""
    return {
        STIMULUS_SOURCE_PARAMS.get(name, name): value
        for name, value in asdict(params).items()
    }
