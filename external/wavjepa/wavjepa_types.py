from typing import TypedDict
from torch import nn


class TransformerLayerCFG(TypedDict):
    d_model : int
    nhead : int
    batch_first : bool
    norm_first : bool
    bias : bool
    dim_feedforward : int
    dropout : float
    layer_norm_eps : float

    @classmethod
    def create(cls, 
    d_model : int = 768,
    nhead : int = 12,
    batch_first : bool = True,
    norm_first : bool = False,
    bias : bool = True,
    mlp_ratio : float = 4.0,
    dropout : float = 0.0,
    layer_norm_eps : float = 1e-6) -> 'TransformerLayerCFG':
        return TransformerLayerCFG(d_model = d_model, 
                                   nhead = nhead, 
                                   batch_first = batch_first,
                                   norm_first = norm_first, 
                                   bias = bias, 
                                   dim_feedforward = int(d_model * mlp_ratio),
                                   dropout = dropout, 
                                   layer_norm_eps = layer_norm_eps)


# Norm needs to be defined by the user!
class TransformerEncoderCFG(TypedDict):
    num_layers : int
    enable_nested_tensor: bool
    mask_check: bool

    @classmethod
    def create(cls, 
    num_layers : int = 12, 
    enable_nested_tensor: bool = False,
    mask_check: bool = True) -> 'TransformerEncoderCFG':
        return TransformerEncoderCFG(num_layers=num_layers, 
                enable_nested_tensor = enable_nested_tensor,
                mask_check = mask_check)