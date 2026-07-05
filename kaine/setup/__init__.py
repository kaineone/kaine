# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""First-run setup wizard for KAINE.

``python -m kaine.setup`` guides a new operator through license acknowledgement,
a hardware scan, module/model/voice selection, optional extras, opt-in research
metrics, and state-encryption, persisting the choices to the gitignored
``config/kaine.operator.toml`` operator override. It NEVER boots the entity and
NEVER modifies the shipped ``config/kaine.toml``.
"""
from __future__ import annotations

from kaine.setup.wizard import WizardResult, run_wizard

__all__ = ["WizardResult", "run_wizard"]
