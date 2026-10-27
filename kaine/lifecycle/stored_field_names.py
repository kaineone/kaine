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


def stimulus_source_params_record(params: object, *, hearing: object | None = None) -> dict[str, Any]:
    """``asdict(params)`` with each renamed field under the name stored data uses.

    With ``hearing`` (the hearing band parameters), the record gains a
    ``hearing_schedule`` entry holding the saturation window, the minimum and
    maximum dwell, and the colour rule ``stage/5``. Without it the record is
    unchanged, so digests written before the hearing schedule existed still match.
    """
    record = {
        STIMULUS_SOURCE_PARAMS.get(name, name): value
        for name, value in asdict(params).items()
    }
    if hearing is not None:
        record["hearing_schedule"] = {
            "saturation_window_seconds": getattr(hearing, "saturation_window_seconds"),
            "min_dwell_seconds": getattr(hearing, "min_dwell_seconds"),
            "max_dwell_seconds": getattr(hearing, "max_dwell_seconds"),
            "colour": "stage/5",
        }
    return record
