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

import importlib.machinery
import importlib.util
import logging
import os
import sys
import types
from pathlib import Path
from typing import Any, Optional

from kaine.model_paths import models_dir

log = logging.getLogger(__name__)

# The pinned upstream commit SHA. MUST equal external/internvideo_next/UPSTREAM
# and the setup-time weight fetch (kaine.setup.internvideo_next).
PINNED_REVISION = "ff2659b9be360a6b1e94b1eb381778a960da6019"

# The single fp16 weights file in the published repo.
WEIGHTS_FILENAME = "model.safetensors"

# Dir the setup step downloads the weights into, under the shared model-weights
# root (``state/models`` locally, git-ignored; ``/models`` on the container's
# kaine-models volume — see kaine.model_paths). Runtime loads ONLY from here —
# never the hub.
DEFAULT_WEIGHTS_DIR = models_dir() / "internvideo_next_base_p14_res224_f16"

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


# --------------------------------------------------------------------------
# Attention backend: eager fallback when flash_attn is unavailable
# --------------------------------------------------------------------------
#
# The vendored modeling module hard-imports flash_attn at module top level
# (``from flash_attn.flash_attn_interface import flash_attn_varlen_qkvpacked_func``
# and three sibling lines) and defaults its backbone to the fused path
# (``use_flash_attn == use_fused_rmsnorm == use_fused_mlp == True``). No prebuilt
# flash_attn wheel exists for this project's torch/CUDA (2.11 / cu128) and the
# source build is a long nvcc compile, so most supported hosts have NO flash_attn.
# The vendored code, however, also carries a complete EAGER path
# (``Attention._naive_attn`` + plain ``Mlp`` + local ``RMSNorm``) selected by
# those three flags being False; it loads the same fp16 checkpoint with zero key
# mismatches and computes standard scaled-dot-product attention. This loader makes
# that eager path the automatic fallback so InternVideo-Next loads on a host
# without flash_attn, WITHOUT editing the byte-identical vendored files.

# The exact symbols the vendored module imports from flash_attn, grouped by the
# submodule that must expose them (see modeling_internvideo_next.py lines 6-7 and
# 320-321). On the eager path these are only *referenced* by fused-only code
# branches that never execute; each stub raises if actually called.
_FLASH_ATTN_STUB_SYMBOLS: dict[str, tuple[str, ...]] = {
    "flash_attn.flash_attn_interface": ("flash_attn_varlen_qkvpacked_func",),
    "flash_attn.bert_padding": ("unpad_input", "pad_input"),
    "flash_attn.modules.mlp": ("FusedMLP",),
    "flash_attn.ops.rms_norm": ("DropoutAddRMSNorm",),
}

# Marker attribute set on the stub package so a second load in the same process
# recognises its own stub in sys.modules and does not mistake it for a real build.
_STUB_MARKER = "_KAINE_EAGER_STUB"


def _make_unavailable(symbol: str):
    """Return a callable that raises a clear RuntimeError if invoked.

    Stands in for a flash_attn symbol on the eager path. It must never be called
    there; if it is, the eager config was not applied and that is a real bug to
    surface loudly — not something to silently no-op.
    """

    def _raise(*_args: Any, **_kwargs: Any):
        raise RuntimeError(
            f"flash_attn.{symbol} was invoked, but no flash_attn is installed and "
            "the InternVideo-Next encoder was built on the eager path "
            "(use_flash_attn=use_fused_rmsnorm=use_fused_mlp=False), which must "
            "never reach the fused kernels. Reaching this means the eager config "
            "was not applied at construction — a bug to fix, not a missing dep."
        )

    return _raise


def _new_module(name: str, *, is_package: bool) -> types.ModuleType:
    """Create a bare module with a proper ModuleSpec for the import machinery."""
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(
        name, loader=None, is_package=is_package
    )
    if is_package:
        mod.__path__ = []  # marks it a package so ``from a.b import c`` resolves
    return mod


def _install_flash_attn_stub() -> None:
    """Register a minimal stub ``flash_attn`` package into ``sys.modules``.

    Exposes exactly the symbols the vendored module imports at top level, so its
    ``from flash_attn... import ...`` lines succeed on a host with no flash_attn.
    Every exposed symbol is a callable that RAISES if called — the eager path only
    references them, never calls them, so a real call is a bug we want to surface.
    """
    flash_attn = _new_module("flash_attn", is_package=True)
    setattr(flash_attn, _STUB_MARKER, True)
    sys.modules["flash_attn"] = flash_attn

    for mod_name, symbols in _FLASH_ATTN_STUB_SYMBOLS.items():
        submod = _new_module(mod_name, is_package=False)
        for symbol in symbols:
            setattr(submod, symbol, _make_unavailable(symbol))
        sys.modules[mod_name] = submod
        # Bind each module onto its parent package so attribute access resolves.
        parent_name, _, child = mod_name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is None:  # intermediate package (e.g. flash_attn.modules)
            parent = _new_module(parent_name, is_package=True)
            sys.modules[parent_name] = parent
            grandparent_name, _, pchild = parent_name.rpartition(".")
            setattr(sys.modules[grandparent_name], pchild, parent)
        setattr(parent, child, submod)

    log.info(
        "flash_attn not installed; registered eager-fallback stub so the vendored "
        "InternVideo-Next module imports and runs on its naive attention path."
    )


def _ensure_attention_backend() -> bool:
    """Prepare the attention backend for the vendored import and report the mode.

    Returns True when a real fused ``flash_attn`` build is importable (the vendored
    fused defaults are used unchanged), False when it is not (a stub is installed
    into ``sys.modules`` and the caller must force the eager config). Must be called
    BEFORE importing the vendored modeling module, whose top-level imports fail
    without either a real flash_attn or the stub.
    """
    existing = sys.modules.get("flash_attn")
    if existing is not None:
        # Already imported this process: real build unless it is our own stub.
        return not getattr(existing, _STUB_MARKER, False)
    if importlib.util.find_spec("flash_attn") is not None:
        return True
    _install_flash_attn_stub()
    return False


def _force_eager_attention(config: Any) -> None:
    """Force the vendored backbone onto its eager path via ``config`` in place.

    The backbone defaults ``use_flash_attn``/``use_fused_rmsnorm``/``use_fused_mlp``
    to True and asserts they are equal; the published checkpoint's ``model_config``
    omits them, so without this the backbone reaches for the fused kernels. Setting
    all three False in the ``model_config`` dict (splatted as kwargs into the
    backbone) selects ``_naive_attn`` + plain ``Mlp`` + local ``RMSNorm`` — the same
    fp16 weights load with zero key mismatches. Kept mutually consistent to satisfy
    the backbone's equality assert.
    """
    model_config = getattr(config, "model_config", None)
    if not isinstance(model_config, dict):
        raise RuntimeError(
            "InternVideo-Next config exposes no 'model_config' dict to force onto "
            "the eager attention backend; cannot safely disable the fused flash_attn "
            "path. Refusing to load."
        )
    model_config["use_flash_attn"] = False
    model_config["use_fused_rmsnorm"] = False
    model_config["use_fused_mlp"] = False


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

    # Resolve the default at CALL time, not from the import-time DEFAULT_WEIGHTS_DIR
    # constant: that constant freezes models_dir() at module import, which can predate
    # KAINE_MODELS_DIR taking effect (observed in the container — the weights live on
    # the /models volume but the frozen constant still pointed at the local
    # state/models default). models_dir() re-reads the env, so call-time is correct.
    if weights_dir is not None:
        wdir = Path(weights_dir)
    else:
        wdir = models_dir() / "internvideo_next_base_p14_res224_f16"
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

    # Select the attention backend BEFORE importing the vendored module (its
    # top-level imports need either a real flash_attn or the stub). On a host with
    # flash_attn the fused path is used unchanged; without it, a stub is installed
    # and the eager config is forced below. Tests inject ``_classes`` and never
    # import the vendored stack, so the backend prep is real-path only.
    force_eager = False
    if _classes is not None:
        config_cls, model_cls = _classes
    else:
        force_eager = not _ensure_attention_backend()
        config_cls, model_cls = _import_vendored_classes()

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
    # No real flash_attn on this host → build the backbone on its eager path so the
    # frozen fp16 weights load and run without the fused kernels (see the eager
    # fallback section above). With flash_attn present this is skipped entirely.
    if force_eager:
        _force_eager_attention(config)
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
