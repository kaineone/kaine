# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""KAINE package initialization."""

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("kaine")
except Exception:  # pragma: no cover - defensive
    __version__ = "0.0.0"

# kaine.audio currently provides only resample_sam_path. No dead re-exports of
# apply_prosody_muffling / SPECTRAL_CEILING_HZ are advertised here.
