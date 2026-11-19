# SPDX-License-Identifier: CAL-0.5

"""Kaine package."""

# Keep kaine.audio exports explicit to preserve public API stability.

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kaine")
except PackageNotFoundError:
    __version__ = "0.0.0"