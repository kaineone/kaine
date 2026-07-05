# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Concrete embodiment adapters behind the Mundus control plane.

Each body the entity can inhabit is one adapter here; the core selects exactly
one at boot. ``opensim`` is the transitional reference/conformance body (the old
OpenSim/LEAP bridge, behavior preserved); ``stub`` is a transport-free reference
body that pins the continuous-channel path. Neither is imported eagerly, so a
missing optional dependency of one adapter never breaks the other.
"""
