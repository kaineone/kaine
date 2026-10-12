# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.vocal.client import (
    ChatterboxClient,
    FakeTTSClient,
    SynthesisResult,
    TTSClient,
    TTSRequest,
)
from kaine.modules.vocal.coordination import SpeakingGate
from kaine.modules.vocal.mapping import (
    ChatterboxParams,
    affect_to_chatterbox,
)
from kaine.modules.vocal.mirroring import blend_prosody, decayed_strength
from kaine.modules.vocal.module import Vocal
from kaine.modules.vocal.playback import (
    FakePlayer,
    NullPlayer,
    Player,
    SoundDevicePlayer,
    build_player,
    wav_duration_s,
)

__all__ = [
    "Vocal",
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
