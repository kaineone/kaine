# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.phantasia.encoder import (
    VERSION as ENCODER_VERSION,
    encode_snapshot,
    observation_dim,
)
from kaine.modules.phantasia.module import Phantasia
from kaine.modules.phantasia.world_model import (
    FakeWorldModel,
    WorldModel,
    load_world_model,
)

__all__ = [
    "ENCODER_VERSION",
    "FakeWorldModel",
    "Phantasia",
    "WorldModel",
    "encode_snapshot",
    "load_world_model",
    "observation_dim",
]
