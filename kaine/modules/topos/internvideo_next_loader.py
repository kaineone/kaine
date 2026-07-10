# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline, no-remote-code loader for the vendored InternVideo-Next encoder.

SECURITY-CRITICAL. This is the whole reason InternVideo-Next's modeling code is
vendored into ``external/internvideo_next/`` (see that dir's ``UPSTREAM`` and
design.md §5). The published HF repo declares ``auto_map`` in ``config.json``, so
the model-card's ``AutoModel.from_pretrained(..., trust_remote_code=True)`` would
DOWNLOAD AND EXECUTE Python from the hub at load time. This loader eliminates that
path entirely. How it avoids remote code / runtime network, concretely:

  1. It imports the config + model classes DIRECTLY from the in-repo vendored
     package ``external.internvideo_next`` — a normal Python import of reviewed,
     pinned, in-tree source. It is NOT the hub's ``trust_remote_code`` cache
     (``~/.cache/huggingface/modules/transformers_modules/...``); nothing is
     fetched to load these classes.
  2. It calls the VENDORED classes' own ``from_pretrained`` (inherited from
     ``transformers`` ``PretrainedConfig`` / ``PreTrainedModel``) — NOT the
     ``Auto*`` factories — so the ``auto_map`` in ``config.json`` is never
     consulted and there is no code-resolution step that could reach the hub.
  3. Every call passes ``trust_remote_code=False`` and ``local_files_only=True``,
     and points at a LOCAL directory (the setup-time weights fetch), so even the
     weights load performs no network I/O.
  4. ``HF_HUB_DISABLE_TELEMETRY=1`` and ``HF_HUB_OFFLINE=1`` are set before any
     transformers call as belt-and-suspenders (no outbound, no hub reachability).

The vendored code revision and the weights revision are pinned to the SAME commit
SHA (``PINNED_REVISION``); a weights snapshot recorded at a different revision is a
load-time error.

Phase 1 ships this loader as a real, tested function. It is invoked by the
InternVideo-Next encoder's forward pass, which is implemented in Phase 2; until
then selecting the ``internvideo_next`` backend fails loudly (never a fake load).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# The pinned upstream commit SHA. MUST equal external/internvideo_next/UPSTREAM
# and the setup-time weight fetch (kaine.setup.internvideo_next).
PINNED_REVISION = "ff2659b9be360a6b1e94b1eb381778a960da6019"

# The single fp16 weights file in the published repo.
WEIGHTS_FILENAME = "model.safetensors"

# Repo-relative dir the setup step downloads the weights into (under state/,
# git-ignored). Runtime loads ONLY from here — never the hub.
DEFAULT_WEIGHTS_DIR = Path("state/models/internvideo_next_base_p14_res224_f16")

# Optional revision marker the setup step / loader use to detect a
# code-vs-weights revision mismatch (see _read_recorded_revision).
_REVISION_MARKER = ".internvideo_next_revision"


def vendored_code_dir() -> Path:
    """Absolute path to the vendored modeling package (external/internvideo_next).

    ``…/kaine/modules/topos/internvideo_next_loader.py`` → repo root is parents[3]."""
    return Path(__file__).resolve().parents[3] / "external" / "internvideo_next"


def _import_vendored_classes() -> tuple[type, type]:
    """Import the vendored config + model classes DIRECTLY from the in-repo package.

    This is a plain import of reviewed, pinned, in-tree source — NOT remote code.
    It is lazy (called only at real load time) because importing the modeling
    module pulls in the vendored code's heavy deps (torch, einops, timm,
    flash_attn, easydict)."""
    from external.internvideo_next.modeling_config import InternVideoNextConfig
    from external.internvideo_next.modeling_internvideo_next import InternVideoNext

    return InternVideoNextConfig, InternVideoNext


def _read_recorded_revision(weights_dir: Path) -> Optional[str]:
    marker = Path(weights_dir) / _REVISION_MARKER
    try:
        return marker.read_text().strip() or None
    except OSError:
        return None


def load_internvideo_next(
    weights_dir: Optional[Any] = None,
    *,
    device: str = "cpu",
    torch_dtype: Any = None,
    revision: str = PINNED_REVISION,
    _classes: Optional[tuple[type, type]] = None,
    _telemetry_env: Optional[dict[str, str]] = None,
) -> Any:
    """Load the vendored InternVideo-Next encoder fully offline, frozen.

    NO remote code, NO network. Returns a frozen (``eval()`` +
    ``requires_grad_(False)``) model on ``device``. See the module docstring for
    the four concrete no-remote-code guarantees.

    ``_classes`` injects ``(config_cls, model_cls)`` for tests (so the security
    kwargs can be asserted without importing the heavy vendored stack); production
    leaves it None → the vendored classes are imported directly. ``_telemetry_env``
    likewise injects the env mapping the loader hardens (defaults to ``os.environ``).
    """
    env = _telemetry_env if _telemetry_env is not None else os.environ
    # Belt-and-suspenders: disable telemetry AND forbid any hub reachability at
    # load. setdefault so an operator-set value is respected.
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    env.setdefault("HF_HUB_OFFLINE", "1")

    wdir = Path(weights_dir) if weights_dir is not None else DEFAULT_WEIGHTS_DIR
    if not wdir.exists():
        raise FileNotFoundError(
            f"InternVideo-Next weights dir not found: {wdir}. Fetch them once at "
            "setup: `python -m kaine.setup.internvideo_next --yes` (or see "
            "kaine.setup.internvideo_next.acquisition_guide()). Runtime never "
            "downloads weights."
        )

    recorded = _read_recorded_revision(wdir)
    if recorded is not None and recorded != revision:
        raise RuntimeError(
            f"InternVideo-Next weights at {wdir} are revision {recorded!r} but the "
            f"vendored code is pinned to {revision!r}; re-fetch the weights at the "
            "pinned revision. Refusing to load a code/weights revision mismatch."
        )

    config_cls, model_cls = _classes if _classes is not None else _import_vendored_classes()

    # Use the VENDORED classes' own from_pretrained (NOT Auto*), with
    # trust_remote_code=False + local_files_only=True. auto_map is never consulted;
    # no code or weights are fetched from the hub.
    #
    # The config lives in the VENDORED, reviewed, revision-pinned in-tree package
    # (external/internvideo_next/config.json) — NOT in the weights dir. The setup
    # fetch pulls only model.safetensors into ``wdir`` (config.json is vendored,
    # not re-downloaded), so the config is read from the vendored dir exactly as
    # the VideoMAE processor is (see encoder._load_videomae_processor). This is
    # also strictly safer than trusting a downloaded config. The weights (the
    # single safetensors) are then loaded from ``wdir`` with the vendored config
    # passed in explicitly, so no config.json is required alongside the weights.
    config = config_cls.from_pretrained(
        str(vendored_code_dir()), local_files_only=True, trust_remote_code=False
    )
    model = model_cls.from_pretrained(
        str(wdir),
        config=config,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch_dtype,
    )

    # Frozen contract (unchanged from DINOv2): eval + no grad; Topos never trains it.
    model.eval()
    for p in model.parameters():
        p.requires_grad_(False)
    model.to(device)
    log.info(
        "InternVideo-Next encoder loaded offline from %s on %s (revision %s, "
        "trust_remote_code=False)",
        wdir,
        device,
        revision,
    )
    return model
