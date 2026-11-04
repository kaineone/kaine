# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""First-hours stop criterion for the development-run stimulus control.

During the first awake hours after stimulus control is switched on, the
paused-share ceiling and the refusal count are stop criteria: a breach means
the entity pauses the programme more than the design allows, and the operator
must review before the run continues.  Past the window the criterion expires
and the regular welfare net covers the remainder.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: The awake-time window in which the criterion applies.
FIRST_HOURS_WINDOW_S = 10800.0

#: The paused-share ceiling: the criterion fires when the maximum trailing-
#: awake-hour paused share *exceeds* this value (strict >).
PAUSED_SHARE_CEILING = 0.20

#: Where the verdict is written, relative to the step's working directory.
VERDICT_RELPATH = "state/lifecycle/stimulus_control_first_hours.json"


def check_first_hours(
    record: dict[str, Any],
    pass_number: int,
    readout_pause: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a verdict dict when the criterion fires, else ``None``."""
    awake_s = record.get("awake_s", 0.0)
    if awake_s > FIRST_HOURS_WINDOW_S:
        return None
    paused_share_max = record.get("paused_share_last_awake_hour_max", 0.0)
    refusals = record.get("pause_share_refusals", 0)
    if paused_share_max > PAUSED_SHARE_CEILING:
        reason = "paused_share_last_awake_hour_max exceeded 0.20"
    elif refusals > 0:
        reason = "pause_share_refusals above 0"
    else:
        return None
    return {
        "verdict": "stopped",
        "rule": "stimulus_control_first_hours",
        "reason": reason,
        "awake_s": awake_s,
        "pass_number": pass_number,
        "paused_share_last_awake_hour_max": paused_share_max,
        "pause_share_refusals": refusals,
        "after_own_act_by_action_pause": readout_pause,
        "record": record,
    }


def write_verdict(verdict: dict[str, Any], line_dir: Path) -> Path:
    """Write the verdict atomically to the step's lifecycle directory."""
    path = line_dir / VERDICT_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(verdict, fh)
    tmp.replace(path)
    log.warning(
        "stimulus_control_first_hours: stopped (pass %d, awake %.0f s, "
        "paused_share_max %.3f, refusals %d): %s",
        verdict.get("pass_number", -1),
        verdict.get("awake_s", 0.0),
        verdict.get("paused_share_last_awake_hour_max", 0.0),
        verdict.get("pause_share_refusals", 0),
        verdict.get("reason", ""),
    )
    return path
