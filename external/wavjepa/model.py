import copy
import numpy as np 

from typing import Any, Optional

import torch
from torch import nn


from .pos_embed import get_1d_sincos_pos_embed_from_grid, get_2d_sincos_pos_embed, get_binaural_pos_embed
from .audio_extractor import Extractor
from .wavjepa_types import TransformerLayerCFG, TransformerEncoderCFG
from .utils import normalize, calculate_padding_mask, get_timestamps

class WavJEPA(nn.Module):
    """
    Joint-Embedding Predictive Architecture (JEPA).

    This implementation is inspired by:
        * I-JEPA http://arxiv.org/abs/2301.08243
        * Data2vec 2.0 http://arxiv.org/abs/2212.07525
    """

    teacher_encoder: nn.Module
    sample_rate : int = 16000
    process_audio_seconds : float = 2.01
    in_channels : int = 1

    
    def __init__(
        self,
        feature_extractor: Extractor,
        transformer_encoder_layers_cfg : TransformerLayerCFG,
        transformer_encoder_cfg : TransformerEncoderCFG,
        transformer_decoder_layers_cfg : TransformerLayerCFG,
        transformer_decoder_cfg : TransformerEncoderCFG,
        size : str = "base",
        **kwargs : dict[str, Any],
    ):
        super().__init__(**kwargs)
    
        self.is_spectrogram = False
        self.target_length = int(self.sample_rate * self.process_audio_seconds)
        self.extract_audio = feature_extractor
        self.total_patches = 200
        self.feature_norms : nn.Module = nn.LayerNorm(self.extract_audio.embedding_dim)

        self.n_encoder_heads = transformer_encoder_layers_cfg["nhead"]
        self.encoder_embedding_dim = transformer_encoder_layers_cfg["d_model"]
        self.n_decoder_heads = transformer_decoder_layers_cfg["nhead"]
        self.decoder_embedding_dim = transformer_decoder_layers_cfg["d_model"]

        encoder_layer = nn.TransformerEncoderLayer(**transformer_encoder_layers_cfg, activation=nn.GELU())
        self.encoder = nn.TransformerEncoder(encoder_layer, norm = nn.LayerNorm(self.encoder_embedding_dim), **transformer_encoder_cfg)
        self.post_extraction_mapper : Optional[nn.Module] = nn.Linear(feature_extractor.embedding_dim, self.encoder_embedding_dim) if feature_extractor.embedding_dim != self.encoder_embedding_dim else None
        decoder_layer = nn.TransformerEncoderLayer(**transformer_decoder_layers_cfg, activation=nn.GELU())
        self.decoder = nn.TransformerEncoder(decoder_layer, norm = nn.LayerNorm(self.decoder_embedding_dim), **transformer_decoder_cfg)
        self.decoder_to_encoder_mapper = nn.Linear(self.decoder_embedding_dim, self.encoder_embedding_dim, bias=True)
        self.encoder_to_decoder_mapper = nn.Linear(self.encoder_embedding_dim, self.decoder_embedding_dim)

        # For the autocast add batch dimensions.
        self.mask_token = nn.Parameter(
            torch.zeros(1, 1, self.decoder_embedding_dim, requires_grad=True)
        )
        self.pos_encoding_encoder = self._get_pos_embed_params(self.encoder_embedding_dim)
        self.pos_encoding_decoder = self._get_pos_embed_params(self.decoder_embedding_dim)
        self.output_steps = self.extract_audio.total_patches(self.target_length) // self.in_channels

        self._init_teacher()


    def _get_pos_embed_params(self, embedding_dim):
        """Calculates the pos embedding embedding parameters and returns them."""
        # Update positional embedding
        pos_embed = nn.Parameter(
            torch.zeros(
                1,
                self.total_patches,
                embedding_dim,
            ),
            requires_grad=False,
        )
        positions = np.arange(self.total_patches, dtype=np.float64)
        if self.is_spectrogram:
            # If it is a spectrogram, we use 2d sincos embeddings.
            pos_embed_data = get_2d_sincos_pos_embed(
                embedding_dim, self.extract_audio.grid_size, cls_token_num=0
            )
        #TODO! Remove this total patches later.
        elif not self.is_spectrogram and self.in_channels == 2 and (self.total_patches == 400):
            # We use 1D sincos embeddings with channel number indicated on the last 384 dimensions.
            pos_embed_data = get_binaural_pos_embed(embedding_dim, time_steps=self.total_patches // self.in_channels
            )
        elif not self.is_spectrogram and self.in_channels == 2 and (self.total_patches == 200):
            #Use 1D pos_embeddings if channel-mixing feature extractor
            pos_embed_data = get_1d_sincos_pos_embed_from_grid(
                embedding_dim,
                positions,
            )     
        elif not self.is_spectrogram and self.in_channels == 1 and (self.total_patches == 200):
            # IF it is plain audio, we used 1d sincos embeddings
            pos_embed_data = get_1d_sincos_pos_embed_from_grid(
                embedding_dim,
                positions,
            )
        else:
            raise Exception(f"Not implemented for more in_channels, {self.in_channels}, {self.total_patches}")
        pos_embed.data.copy_(torch.from_numpy(pos_embed_data).float().unsqueeze(0))
        return pos_embed

    def _init_teacher(self):
        self.teacher_encoder = copy.deepcopy(self.encoder)
        self.teacher_encoder.requires_grad_(False)



    @torch.inference_mode()
    def _get_segment_representation(self, audio : torch.Tensor, padding_mask : torch.tensor):
        # Get the audio representatin of waveform x.
        local_features = self.extract_audio(audio)
        local_features = self.feature_norms(local_features)
        if self.post_extraction_mapper:
            local_features = self.post_extraction_mapper(local_features)
        local_features = local_features + self.pos_encoding_encoder
        # Encoder and decoder forward
        contextual_features = self.encoder(local_features, src_key_padding_mask = padding_mask)
        return contextual_features

    @torch.inference_mode()
    def get_audio_representation(self, audio : torch.Tensor):
        B = audio.shape[0]
        input_audio_len = audio.shape[-1]
        # Assert audio is of correct shape
        if audio.ndim != 3:
            raise ValueError(
                "audio input tensor must be 2D with shape (n_sounds, n_channels, num_samples)"
            )
        cur_frames = audio.shape[-1]
        pad_frames = self.target_length - (cur_frames % self.target_length)
        if pad_frames > 0:
            # Padding with constant 0s
            pad_arg = (
                0,
                pad_frames,
            )  # (channel, channel, height, height, width, width)
            audio = torch.nn.functional.pad(audio, pad_arg, mode="constant")
        embeddings = []
        padding_mask, cut_off = calculate_padding_mask(pad_frames = pad_frames, 
                                        total_frames = audio.shape[-1], 
                                        sr = self.sample_rate,
                                        output_steps = self.total_patches,
                                        process_seconds = self.target_length // self.sample_rate, 
                                        device = audio.device, 
                                        B = B)
        mask_idx = 0
        masked_mean = torch.zeros(audio.shape, dtype = torch.bool)
        masked_mean[..., cur_frames:] = True
        mt = torch.masked.masked_tensor(audio, masked_mean)
        # Now get the embeddings o the model.
        for i in range(audio.shape[-1] // self.target_length):
            mt = audio[..., i * self.target_length : (i + 1) * self.target_length]
            mask = padding_mask[...,mask_idx : mask_idx + self.output_steps]
            with torch.no_grad():
                # We do not include padding tokens in the mean and std calculation.
                embedding = self._get_segment_representation(
                    normalize(mt),
                    mask
                )
            mask_idx = mask_idx + self.output_steps
            embeddings.append(embedding)

        x = torch.hstack(embeddings)
        x = x[:, :cut_off, :]
        ts = get_timestamps(self.sample_rate, B, input_audio_len, x)
        return x, ts 



