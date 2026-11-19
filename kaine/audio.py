# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import librosa
import numpy as np


def resample_sam_path(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr, res_type="soxr_hq")
