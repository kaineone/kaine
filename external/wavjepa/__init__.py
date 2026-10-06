# SPDX-License-Identifier: MIT
# Vendored from labhamlet/wavjepa-base at the pinned revision recorded in
# `UPSTREAM`, with the two eval() removals and the types.py rename listed there.
#
# Importing `modeling_wavjepa` pulls in torch, einops and transformers; the KAINE
# loader imports it lazily, only when the WavJEPA encoder is selected.
