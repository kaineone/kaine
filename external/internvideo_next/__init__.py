# SPDX-License-Identifier: MIT
# Vendored from OpenGVLab InternVideo-Next at the pinned revision recorded in
# `UPSTREAM` (repo, commit SHA, MIT license text, and the literal-vendor
# rationale). Copyright (c) 2025 OpenGVLab / InternVideo-Next authors.
#
# This package holds a BYTE-IDENTICAL copy of the upstream modeling source so the
# encoder can be loaded with `trust_remote_code=False` from a local directory —
# no code is fetched or executed from the Hugging Face hub at runtime. See
# `kaine/modules/topos/internvideo_next_loader.py` for the offline, no-remote-code
# loader and design.md §5 of the topos-temporal-video-encoder change.
#
# The upstream `.py` files in this directory are intentionally left byte-identical
# to the pinned revision (no injected headers) so the provenance diff against the
# hub stays clean; the SPDX identifier and attribution live in this file and in
# `UPSTREAM`.
#
# NOTE: importing `modeling_internvideo_next` pulls in torch, einops, timm,
# flash_attn, and easydict (the vendored code's dependencies). It is imported
# LAZILY by the loader only when the InternVideo-Next backend is actually loaded
# (Phase 2); the rest of the package never triggers that import.

PINNED_REVISION = "ff2659b9be360a6b1e94b1eb381778a960da6019"
