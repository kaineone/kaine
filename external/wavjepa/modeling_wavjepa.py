from transformers import PreTrainedModel

from .model import WavJEPA
from .configuration_wavjepa import WavJEPAConfig
from .audio_extractor import ConvFeatureExtractor
import ast
import torch 
from typing import Union 


# KAINE: the upstream code passed this config string to eval(). It is parsed
# here instead, accepting only integer tuples, lists, "+" and "*" (for example
# "[(512, 10, 5)] + [(512, 3, 2)] * 4 + [(512,2,2)]"); anything else is refused.
def parse_conv_layers_spec(spec):
    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(_ev(e) for e in node.elts)
        if isinstance(node, ast.List):
            return [_ev(e) for e in node.elts]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
            left, right = _ev(node.left), _ev(node.right)
            if isinstance(node.op, ast.Add) and isinstance(left, list) and isinstance(right, list):
                return left + right
            if isinstance(node.op, ast.Mult) and isinstance(left, list) and type(right) is int:
                return left * right
        raise ValueError(f"unsupported conv_layers_spec: {spec!r}")

    if not isinstance(spec, str):
        raise ValueError(f"conv_layers_spec must be a string, got {type(spec).__name__}")
    return _ev(ast.parse(spec, mode="eval"))

class WavJEPAModel(PreTrainedModel):
    config_class = WavJEPAConfig

    def __init__(self, config):
        super().__init__(config)

        self.model = WavJEPA(
                feature_extractor = ConvFeatureExtractor(
                    conv_layers_spec = parse_conv_layers_spec(config.extractor_config['conv_layers_spec']),
                    in_channels = config.extractor_config['in_channels'],
                    dropout = config.extractor_config['dropout'],
                    mode = config.extractor_config['mode'],
                    conv_bias = config.extractor_config['conv_bias'],
                    depthwise = config.extractor_config['depthwise'],
                    ),
                transformer_encoder_layers_cfg = config.encoder_layers_cfg,
                transformer_encoder_cfg = config.encoder_cfg,
                transformer_decoder_layers_cfg = config.decoder_layers_cfg,
                transformer_decoder_cfg = config.decoder_cfg,
                size = config.model_size,
        )

    def forward(self, tensor) -> Union[torch.Tensor, torch.Tensor]:
        return self.model.get_audio_representation(tensor)

