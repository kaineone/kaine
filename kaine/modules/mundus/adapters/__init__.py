# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Concrete embodiment adapters behind the Mundus control plane.

Each body the entity can inhabit is one adapter here; the core selects exactly
one at boot. ``stub`` is the shipped reference body: a transport-free, wholly
local adapter that pins the protocol — including the continuous-channel path — so
the body-agnostic core is exercised end to end without any external world. No
transport-backed body ships today; a virtual-world (Paracosmic) adapter is
planned. Adapters are not imported eagerly, so a missing optional dependency of
one never breaks another.
"""
