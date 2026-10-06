from typing import Optional, Union
import numpy as np

from transformers import SequenceFeatureExtractor
from transformers import BatchFeature
from transformers.utils import TensorType 

import torch 


class WavJEPAFeatureExtractor(SequenceFeatureExtractor):
    in_channels = 1
    feature_extractor_type = "wavjepa-base"

    def __init__(
        self,
        feature_size=1,
        sampling_rate=16000,
        padding_value=0.0,
        **kwargs,
    ):
        super().__init__(feature_size=feature_size, sampling_rate=sampling_rate, padding_value=padding_value, **kwargs)

    def _extract_features(
        self,
        audio: np.ndarray,
    ) -> np.ndarray:

        audio = torch.tensor(audio)
        # Normalize input audio
        if (audio.ndim == 2) and (audio.shape[0] > 100):
            audio = audio.transpose(1,0)
        if audio.ndim == 1:
            audio = audio.unsqueeze(0)
            
        audio = self._normalize_audio(audio, -14.0)
        if audio.shape[0] == 1:
            return audio
        elif audio.shape[0] == 2:
            audio  = audio.mean(axis = 0).unsqueeze(0)  
            return audio
        elif audio.shape[0] == 4:
            audio  = audio[0].unsqueeze(0)
            return audio
        else:
            raise Exception("Unknowm channel count")  
        

    def _normalize_audio(self, audio_data, target_dBFS=-14.0):
        rms = torch.sqrt(torch.mean(audio_data**2))  # Calculate the RMS of the audio
        if rms == 0:  # Avoid division by zero in case of a completely silent audio
            return audio_data
        current_dBFS = 20 * torch.log10(rms)  # Convert RMS to dBFS
        gain_dB = target_dBFS - current_dBFS  # Calculate the required gain in dB
        gain_linear = 10 ** (gain_dB / 20)  # Convert gain from dB to linear scale
        normalized_audio = audio_data * gain_linear  # Apply the gain to the audio data
        return normalized_audio

    def __call__(
        self,
        raw_speech: Union[np.ndarray, list[float], list[np.ndarray], list[list[float]]],
        sampling_rate: Optional[int] = None,
        return_tensors: Optional[Union[str, TensorType]] = None,
        **kwargs,
    ) -> BatchFeature:
        """
        Main method to featurize and prepare for the model one or several sequence(s).

        Args:
            raw_speech (`np.ndarray`, `list[float]`, `list[np.ndarray]`, `list[list[float]]`):
                The sequence or batch of sequences to be padded. Each sequence can be a numpy array, a list of float
                values, a list of numpy arrays or a list of list of float values.

            sampling_rate (`int`, *optional*):
                The sampling rate at which the `raw_speech` input was sampled. It is strongly recommended to pass
                `sampling_rate` at the forward call to prevent silent errors.
            return_tensors (`str` or [`~utils.TensorType`], *optional*):
                If set, will return tensors instead of list of python integers. Acceptable values are:

                - `'tf'`: Return TensorFlow `tf.constant` objects.
                - `'pt'`: Return PyTorch `torch.Tensor` objects.
                - `'np'`: Return Numpy `np.ndarray` objects.
        """

        if sampling_rate is not None:
            if sampling_rate != self.sampling_rate:
                raise ValueError(
                    f"The model corresponding to this feature extractor: {self} was trained using a sampling rate of"
                    f" {self.sampling_rate}. Please make sure that the provided `raw_speech` input was sampled with"
                    f" {self.sampling_rate} and not {sampling_rate}."
                )

        # extract fbank features and pad/truncate to max_length
        features = [self._extract_features(waveform) for waveform in raw_speech]
        features = torch.nn.utils.rnn.pad_sequence(features, batch_first=True)
        inputs = BatchFeature({"input_values": features})
        return inputs


