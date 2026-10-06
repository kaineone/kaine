# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""A native service start records its pid only once the child is the service.

Between fork and exec a backgrounded child's command line is still the
bootstrap script's. A bootstrap that wrote the pidfile and exited in that
window left a pid the next run could not recognise, so the next run called the
pidfile stale and started a second copy. These tests run the real shell helper.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "native-services.sh"

# The service name is assembled at run time so that the bash -c script text,
# which is the child's command line until it execs, never contains it.
_PRELUDE = f'source "{LIB}"; svc_name=redis-ser; svc_name="${{svc_name}}ver"; '


def _bash(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", _PRELUDE + script], capture_output=True, text=True, timeout=30
    )


def test_wait_exec_waits_for_a_child_that_execs_late():
    r = _bash(
        '( sleep 1; exec -a "$svc_name" sleep 30 ) & pid=$!; '
        'if native_pid_is_ours redis "$pid"; then echo EARLY; fi; '
        'if native_wait_exec redis "$pid"; then echo READY; fi; '
        'native_pid_is_ours redis "$pid" && echo OURS; '
        'kill "$pid"'
    )
    assert "EARLY" not in r.stdout, "the child must not look like the service before it execs"
    assert "READY" in r.stdout, r.stderr
    assert "OURS" in r.stdout, r.stderr


def test_wait_exec_reports_a_child_that_died():
    r = _bash('( exit 0 ) & pid=$!; sleep 0.2; native_wait_exec redis "$pid"; echo "rc=$?"')
    assert "rc=1" in r.stdout, r.stdout + r.stderr
