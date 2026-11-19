# SPDX-License-Identifier: MIT
"""
SAM generator utilities.

This module provides the `load_sam_model` function which loads a SAM (custom
voice) model from a v2 checkpoint.  For local checkpoint paths the function
asserts that the accompanying checkpoint configuration contains the expected
values:

* ``spk_id["sam"]`` must be ``3000``.
* ``tts_model_type`` must be ``"custom_voice"``.

If the configuration file is missing or the values do not match, an exception
is raised – no silent fallback is performed.
"""

import os
import json
import logging
from urllib.parse import urlparse
from typing import Any

# NOTE: The actual model class may live in a different module.  The import is
# performed lazily inside the function to avoid circular imports and to keep
# the module import‑time lightweight.
# If a dedicated model loader is used in the original codebase, replace the
# placeholder import below with the appropriate one.
# from .model import SamModel  # type: ignore

def load_sam_model(v2_checkpoint_path: str) -> Any:
    """
    Load a SAM (custom voice) model from a v2 checkpoint.

    For **local** checkpoint paths, the function asserts that the associated
    configuration JSON contains the required entries:
    ``spk_id["sam"] == 3000`` and ``tts_model_type == "custom_voice"``.
    If the configuration is missing or the assertions fail, an exception is
    raised – the function does **not** silently fall back to a default model.

    Parameters
    ----------
    v2_checkpoint_path:
        Path or URL pointing to the SAM checkpoint file.

    Returns
    -------
    Any
        The loaded SAM model instance (type depends on the underlying
        implementation).

    Raises
    ------
    ValueError
        If ``v2_checkpoint_path`` is an empty string.
    FileNotFoundError
        If the expected configuration file cannot be found for a local
        checkpoint.
    AssertionError
        If the configuration does not contain the required values.
    RuntimeError
        If the underlying model loading routine fails.
    """
    if not v2_checkpoint_path:
        raise ValueError("v2_checkpoint_path must be a non‑empty string")

    # ----------------------------------------------------------------------
    # Determine whether the checkpoint is a local filesystem path or a remote
    # URL.  Remote URLs are identified by a URL scheme (e.g. http:// or https://).
    # ----------------------------------------------------------------------
    parsed = urlparse(v2_checkpoint_path)
    is_local_path = not parsed.scheme

    # ----------------------------------------------------------------------
    # For local paths we enforce the presence of a JSON configuration file
    # alongside the checkpoint and validate its contents.
    # ----------------------------------------------------------------------
    if is_local_path:
        # Possible configuration filenames that may be used by the project.
        cfg_dir = os.path.dirname(v2_checkpoint_path)
        cfg_candidates = [
            os.path.join(cfg_dir, "config.json"),
            os.path.join(cfg_dir, "checkpoint_config.json"),
            os.path.join(cfg_dir, "v2_config.json"),
        ]

        cfg_path = next((p for p in cfg_candidates if os.path.isfile(p)), None)

        if cfg_path is None:
            raise FileNotFoundError(
                f"Checkpoint configuration file not found for local checkpoint "
                f"{v2_checkpoint_path!r}. Expected one of: {cfg_candidates}"
            )

        # Load and validate the JSON configuration.
        with open(cfg_path, "r", encoding="utf-8") as cfg_file:
            cfg = json.load(cfg_file)

        spk_id = cfg.get("spk_id", {})
        assert spk_id.get("sam") == 3000, (
            f"Invalid spk_id for SAM checkpoint: expected 3000, got "
            f"{spk_id.get('sam')!r}"
        )
        assert cfg.get("tts_model_type") == "custom_voice", (
            f"Invalid tts_model_type for SAM checkpoint: expected "
            f"'custom_voice', got {cfg.get('tts_model_type')!r}"
        )

    # ----------------------------------------------------------------------
    # Preserve the original model loading logic.  The concrete loading
    # routine may differ between projects; this placeholder uses a generic torch
    # load which works for typical .pth checkpoints.  Adjust as needed.
    # ----------------------------------------------------------------------
    try:
        # Lazy import to keep module load cheap and avoid circular imports.
        import torch
        model = torch.load(v2_checkpoint_path, map_location="cpu")
    except Exception as exc:
        logging.error("Failed to load SAM model from %s: %s", v2_checkpoint_path, exc)
        raise RuntimeError(f"Failed to load SAM model from {v2_checkpoint_path!r}") from exc

    return model