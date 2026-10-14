# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Per-module CL1 backends.

Each backend implements the *exact client interface* a KAINE module already
expects for its forward model (e.g. the sequence module's CfC network, the interoception module's
`SubstrateForwardModel`), but realises it on the shared biological substrate via
`kaine_cl1.substrate`. The backend is injected at construction by
`kaine_cl1.boot`; the KAINE module body is unchanged and unaware.

Strong-tier backends (full conversions, planned): `sequence`, `interoception`, `planning`,
`oscillator`. Hybrid-tier (silicon + wetware together within one module,
sometimes permanent): `audition_frontend`, `world_model_surprise`, `action_selection`,
`affect`. See `openspec/` for the per-module change proposals and their status.
"""
