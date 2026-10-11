# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Private, capped log file setup for the KAINE entity.

This module is stdlib-only outside the logging package.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _SecureRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler whose rotated files are also created mode 0600."""

    def _open(self):
        fd = os.open(
            self.baseFilename,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        return os.fdopen(fd, self.mode, encoding=self.encoding)


def install_private_log_file(
    path: Path,
    *,
    level: int = logging.NOTSET,
    max_bytes: int = 5 * 2**20,
    backup_count: int = 4,
) -> logging.Handler:
    """Install a private, capped, stderr-replacing log file.

    * The parent directory is created/forced to mode 0700.
    * Every log file (including rotations) is created mode 0600.
    * The format matches the cycle's ``basicConfig`` format.
    * Existing root ``StreamHandler`` outputs to stderr are removed.
    * Python warnings are captured.
    """
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)

    handler = _SecureRotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))

    root = logging.getLogger()
    root.addHandler(handler)

    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr:
            root.removeHandler(h)

    logging.captureWarnings(True)
    return handler
