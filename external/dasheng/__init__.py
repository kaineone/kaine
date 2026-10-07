# SPDX-License-Identifier: Apache-2.0
# Vendored from mispeech/dasheng-base at the pinned revision recorded in
# `UPSTREAM`. Copyright 2023-2024 Xiaomi Corporation and HuggingFace Inc. team.
#
# The upstream `.py` files here are byte-identical to the pinned revision, so the
# provenance diff against the hub stays clean; attribution lives in this file and
# in `UPSTREAM`. Importing `modeling_dasheng` pulls in torch, torchaudio, einops
# and transformers; the KAINE loader imports it lazily, only when the Dasheng
# encoder is selected.
