# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.world_model.backend import (
    FakeWorldModel,
    WorldModelBackend,
    load_world_model,
)
from kaine.modules.world_model.encoder import (
    VERSION as ENCODER_VERSION,
)
from kaine.modules.world_model.encoder import (
    encode_snapshot,
    observation_dim,
)
from kaine.modules.world_model.module import WorldModel

__all__ = [
    "ENCODER_VERSION",
    "FakeWorldModel",
    "WorldModel",
    "WorldModelBackend",
    "encode_snapshot",
    "load_world_model",
    "observation_dim",
]
