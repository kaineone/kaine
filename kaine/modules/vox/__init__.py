# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.vox.client import (
    ChatterboxClient,
    FakeTTSClient,
    SynthesisResult,
    TTSClient,
    TTSRequest,
)
from kaine.modules.vox.coordination import SpeakingGate
from kaine.modules.vox.mapping import (
    ChatterboxParams,
    affect_to_chatterbox,
)
from kaine.modules.vox.mirroring import blend_prosody, decayed_strength
from kaine.modules.vox.module import Vox
from kaine.modules.vox.playback import (
    FakePlayer,
    NullPlayer,
    Player,
    SoundDevicePlayer,
    build_player,
    wav_duration_s,
)

__all__ = [
    "Vox",
    "ChatterboxClient",
    "ChatterboxParams",
    "FakePlayer",
    "FakeTTSClient",
    "NullPlayer",
    "Player",
    "SoundDevicePlayer",
    "SpeakingGate",
    "SynthesisResult",
    "TTSClient",
    "TTSRequest",
    "affect_to_chatterbox",
    "blend_prosody",
    "build_player",
    "decayed_strength",
    "wav_duration_s",
]
