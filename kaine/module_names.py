# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""One source for module names (module-core design D3).

Every product module's ``BaseModule.name`` is recorded here exactly as it is;
this module does not rename or normalize them. ``kaine/legacy_names.py`` maps
retired module names to these. It is a boundary-neutral home (pure data, no
imports), so the workspace and the cycle may import it, which they may not do
with anything under ``kaine.modules``.
"""

AFFECT = "affect"
AUDITION = "audition"
EFFECTORS = "effectors"
EMBODIMENT = "embodiment"
EPISODIC_MEMORY = "episodic_memory"
INTEROCEPTION = "interoception"
LANGUAGE = "language"
PERCEPTUAL_LOCUS = "perceptual_locus"
PLANNING = "planning"
SELF_MODEL = "self_model"
SEQUENCE = "sequence"
SLEEP = "sleep"
SOCIAL_COGNITION = "social_cognition"
VISION = "vision"
VOCAL = "vocal"
WORLD_MODEL = "world_model"

MODULE_NAMES: frozenset[str] = frozenset(
    {
        AFFECT,
        AUDITION,
        EFFECTORS,
        EMBODIMENT,
        EPISODIC_MEMORY,
        INTEROCEPTION,
        LANGUAGE,
        PERCEPTUAL_LOCUS,
        PLANNING,
        SELF_MODEL,
        SEQUENCE,
        SLEEP,
        SOCIAL_COGNITION,
        VISION,
        VOCAL,
        WORLD_MODEL,
    }
)
