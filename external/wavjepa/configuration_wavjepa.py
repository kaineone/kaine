from transformers import PretrainedConfig
from torch import nn 
from .wavjepa_types import TransformerLayerCFG, TransformerEncoderCFG



class WavJEPAConfig(PretrainedConfig):
    model_type = "wavjepa-base"
    model_size = "base"
    in_channels: int = 1

    def __init__(
        self,
        extractor_layers_spec: str = "[(512, 10, 5)] + [(512, 3, 2)] * 4 + [(512,2,2)]",
        extractor_dropout : float = 0.0,
        extractor_mode : str = "default", 
        extractor_conv_bias : bool = False, 
        extractor_depthwise: bool = False,
        encoder_d_model: int = 768,
        encoder_nhead : int = 12,
        encoder_batch_first = True,
        encoder_norm_first = False, 
        encoder_bias = True,
        encoder_mlp_ratio = 4.0,
        encoder_dropout = 0.0,
        encoder_num_layers: int = 12,
        encoder_enable_nested_tensor = False, 
        encoder_mask_check = True,
        decoder_d_model: int = 384,
        decoder_nhead : int = 12,
        decoder_batch_first = True,
        decoder_norm_first = False, 
        decoder_bias = True,
        decoder_mlp_ratio = 4.0,
        decoder_dropout = 0.0,
        decoder_num_layers: int = 12,
        decoder_enable_nested_tensor = False, 
        decoder_mask_check = True,
        **kwargs
    ):
        self.encoder_cfg = TransformerEncoderCFG.create(
                        num_layers = encoder_num_layers,
                        enable_nested_tensor = encoder_enable_nested_tensor,
                        mask_check = encoder_mask_check,
        )
        self.decoder_cfg = TransformerEncoderCFG.create(
                        num_layers = decoder_num_layers,
                        enable_nested_tensor = decoder_enable_nested_tensor,
                        mask_check = decoder_mask_check,
        )
        
        self.encoder_layers_cfg = TransformerLayerCFG.create(
                        d_model = encoder_d_model,
                        nhead = encoder_nhead,
                        batch_first = encoder_batch_first,
                        norm_first = encoder_norm_first,
                        bias = encoder_bias,
                        mlp_ratio = encoder_mlp_ratio,
                        dropout = encoder_dropout,
                        layer_norm_eps = 1e-6
        )
        self.decoder_layers_cfg = TransformerLayerCFG.create(
                        d_model = decoder_d_model,
                        nhead = decoder_nhead,
                        batch_first = decoder_batch_first,
                        norm_first = decoder_norm_first,
                        bias = decoder_bias,
                        mlp_ratio = decoder_mlp_ratio,
                        dropout = decoder_dropout,
                        layer_norm_eps = 1e-6
        )
        self.extractor_config = dict(
                conv_layers_spec = extractor_layers_spec,
                in_channels = self.in_channels,
                dropout = extractor_dropout,
                mode = extractor_mode,
                conv_bias = extractor_conv_bias,
                depthwise = extractor_depthwise)

        super().__init__(**kwargs)