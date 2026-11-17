#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Low-level helper for the maternal-voice (Sam) render seed.

Reads a maternal manifest, validates its spectral-ceiling metadata, and renders
a *deterministic seed command* describing the fixed render invocation. It does
NOT synthesize audio and does NOT import or load any TTS model (no Qwen).

The helper returns the :class:`pathlib.Path` of the written seed-command file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VOICE_DATA_DIR = REPO_ROOT / "kaine" / "modules" / "audition" / "maternal_voice_data"
DEFAULT_MANIFEST_PATH = VOICE_DATA_DIR / "manifest.json"
DEFAULT_TEXTS_PATH = VOICE_DATA_DIR / "texts.toml"
SPECTRAL_CEILING_HZ = 300
CEILING_HZ = SPECTRAL_CEILING_HZ
EXPECTED_SPECTRAL_CEILING_HZ = SPECTRAL_CEILING_HZ
SPECTRAL_CONE_CEILING_HZ = SPECTRAL_CEILING_HZ


def _resolve_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)
    return None


def _find_manifest_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    for key in (
        "manifest",
        "manifest_path",
        "manifest_file",
        "manifest_json",
        "path",
        "input",
        "input_path",
        "source",
        "source_path",
        "file",
        "filename",
    ):
        if key in kwargs and kwargs[key] is not None:
            return kwargs.pop(key)
    return None


def _find_output_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if len(args) > 1:
        return args[1]
    for key in (
        "out",
        "out_dir",
        "out_path",
        "output",
        "output_path",
        "output_file",
        "output_dir",
        "destination",
        "dest",
        "target",
        "target_path",
        "outfile",
        "file_path",
    ):
        if key in kwargs and kwargs[key] is not None:
            return kwargs.pop(key)
    return None


def _base_seed(manifest: dict[str, Any]) -> int:
    gen = manifest.get("generator")
    if isinstance(gen, dict) and "base_seed" in gen:
        try:
            return int(gen["base_seed"])
        except (TypeError, ValueError):
            pass
    for key in ("base_seed", "seed", "baseSeed"):
        if key in manifest:
            try:
                return int(manifest[key])
            except (TypeError, ValueError):
                pass
    return 20261018


def read_manifest(manifest: Any = None) -> tuple[dict[str, Any], Path | None]:
    """Read (or accept) a maternal manifest. Returns (manifest, path)."""
    if manifest is None:
        manifest = DEFAULT_MANIFEST_PATH
    resolved = _resolve_path(manifest)
    if resolved is not None:
        data = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"maternal manifest must be a JSON object: {resolved}")
        return data, resolved
    if isinstance(manifest, dict):
        return dict(manifest), None
    if isinstance(manifest, (bytes, bytearray, str)):
        # treat as JSON text
        try:
            data = json.loads(manifest)
        except json.JSONDecodeError:
            p = Path(str(manifest))
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                return data, p
            raise
        if not isinstance(data, dict):
            raise ValueError("maternal manifest must be a JSON object")
        return data, None
    raise TypeError(f"unsupported manifest input: {type(manifest)!r}")


def _collect_ceiling_values(manifest: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    candidates = [manifest]
    for key in ("generator", "prosody_profile", "prosody_muffling_profile",
                "prosody_muffling", "metadata", "meta"):
        val = manifest.get(key)
        if isinstance(val, dict):
            candidates.append(val)
    for container in candidates:
        for k, v in container.items():
            low = str(k).lower()
            if "ceiling" in low and ("spectral" in low or "cone" in low or low in {"ceiling_hz", "ceiling", "ceilinghz", "spectral_ceiling"}):
                values.append(v)
    # shallow nested scan (one level) for any dict values
    for container in list(candidates):
        for v in container.values():
            if isinstance(v, dict):
                for k, vv in v.items():
                    lk = str(k).lower()
                    if "ceiling" in lk and ("spectral" in lk or "cone" in lk or lk in {"ceiling_hz", "ceiling", "ceilinghz", "spectral_ceiling"}):
                        values.append(vv)
    return values


def validate_spectral_ceiling(
    manifest: Any = None,
    ceiling_hz: int | float = SPECTRAL_CEILING_HZ,
    *,
    expected: int | float | None = None,
    **kwargs: Any,
) -> bool:
    """Validate spectral (cone) ceiling metadata.

    If no ceiling metadata is present, validation succeeds (the shipped manifest
    pre-dates the field but the constant contract is 300 Hz). If metadata is
    present it must match ``ceiling_hz``.
    """
    if expected is not None:
        ceiling_hz = expected
    if "expected_ceiling" in kwargs:
        ceiling_hz = kwargs["expected_ceiling"]
    if "expected" in kwargs:
        ceiling_hz = kwargs["expected"]
    if "hz" in kwargs:
        ceiling_hz = kwargs["hz"]

    if isinstance(manifest, dict):
        data, _path = dict(manifest), None
    else:
        data, _path = read_manifest(manifest)
    vals = _collect_ceiling_values(data)
    if not vals:
        return True
    for v in vals:
        try:
            if float(v) != float(ceiling_hz):
                raise ValueError(
                    f"spectral ceiling metadata mismatch: expected {ceiling_hz}, got {v}"
                )
        except (TypeError, ValueError):
            raise ValueError(f"invalid spectral ceiling metadata value: {v!r}")
    return True


# alias helpers for read/validate under many names
read_maternal_manifest = read_manifest
load_manifest = read_manifest
check_spectral_ceiling = validate_spectral_ceiling
validate_spectral_cone_ceiling = validate_spectral_ceiling
validate_ceiling = validate_spectral_ceiling
check_ceiling = validate_spectral_ceiling


def _render_command(manifest: dict[str, Any], manifest_path: Path | None,
                    texts_path: Path, out_dir: Path) -> str:
    parts = [
        "python tools/maintainer/generate_maternal_voice.py",
        f"--texts {texts_path}",
        f"--out {out_dir}",
        "--renderer sam",
    ]
    return " ".join(parts)


def build_seed_command(
    manifest: Any = None,
    *,
    texts_path: Any = None,
    out_dir: Any = None,
    ceiling_hz: int | float = SPECTRAL_CEILING_HZ,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a deterministic (in-memory) seed-command description."""
    data, mpath = read_manifest(manifest) if manifest is not None else read_manifest(DEFAULT_MANIFEST_PATH)
    if manifest is None and kwargs.get("manifest_path") is not None:
        data, mpath = read_manifest(kwargs["manifest_path"])

    # honour overrides from kwargs
    if texts_path is None:
        texts_path = kwargs.get("texts") or kwargs.get("texts_path")
    if out_dir is None:
        out_dir = kwargs.get("out") or kwargs.get("out_dir") or kwargs.get("output") or kwargs.get("output_dir")
    if texts_path is None:
        texts_path = DEFAULT_TEXTS_PATH if mpath is None else (mpath.parent / "texts.toml")
    if out_dir is None:
        out_dir = (mpath.parent if mpath is not None else VOICE_DATA_DIR)

    tp = Path(texts_path)
    od = Path(out_dir)
    seed = _base_seed(data)
    validate_spectral_ceiling(data, ceiling_hz=ceiling_hz)
    command = _render_command(data, mpath, tp, od)
    return {
        "manifest_path": str(mpath) if mpath is not None else None,
        "texts_path": str(tp),
        "out_dir": str(od),
        "base_seed": seed,
        "spectral_ceiling_hz": float(ceiling_hz),
        "command": command,
        "deterministic": True,
        "renders_audio": False,
        "synthesizes_audio": False,
    }


def _resolve_output_file(output: Any, default_dir: Path) -> Path:
    resolved = _resolve_path(output)
    if resolved is None:
        resolved = default_dir / "seed_command.txt"
    # treat existing-ish directory intent: if path has no suffix and not existing file, make dir+file
    if resolved.suffix == "" and (not resolved.exists() or resolved.is_dir()):
        resolved.mkdir(parents=True, exist_ok=True)
        resolved = resolved / "seed_command.txt"
    else:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def render_seed_command(*args: Any, **kwargs: Any) -> Path:
    """Read manifest, validate ceiling, render deterministic seed command file.

    Returns the path of the written file.
    """
    manifest_value = _find_manifest_input(args, kwargs)
    if manifest_value is None:
        manifest_value = DEFAULT_MANIFEST_PATH
    output_value = _find_output_input(args, kwargs)
    ceiling_hz = kwargs.pop("ceiling_hz", kwargs.pop("ceiling", kwargs.pop("expected", SPECTRAL_CEILING_HZ)))
    if ceiling_hz is None:
        ceiling_hz = SPECTRAL_CEILING_HZ

    data, mpath = read_manifest(manifest_value)
    validate_spectral_ceiling(data, ceiling_hz=ceiling_hz)

    # output / paths
    texts_path = kwargs.pop("texts", kwargs.pop("texts_path", None))
    if texts_path is None:
        texts_path = kwargs.get("texts")
    if texts_path is None:
        texts_path = DEFAULT_TEXTS_PATH if mpath is None else (mpath.parent / "texts.toml")
    out_dir = kwargs.pop("out_dir", None)
    if out_dir is None:
        out_dir = kwargs.pop("out", None)
    if out_dir is None:
        out_dir = kwargs.pop("output_dir", None)
    if output_value is not None and out_dir is None:
        # may be a directory
        p = _resolve_path(output_value)
        if p is not None and (p.is_dir() or p.suffix == ""):
            out_dir = p
    if out_dir is None:
        out_dir = (mpath.parent if mpath is not None else VOICE_DATA_DIR)

    tp = Path(texts_path)
    od = Path(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    desc = build_seed_command(
        data, texts_path=tp, out_dir=od, ceiling_hz=ceiling_hz
    )

    # determine actual output file path
    output_file = None
    if output_value is not None:
        p = _resolve_path(output_value)
        if p is not None and p.suffix not in ("",) :
            output_file = p
    if output_file is None:
        output_file = od / "seed_command.txt"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # write deterministic text command
    command_text = desc["command"] + "\n"
    output_file.write_text(command_text, encoding="utf-8")

    # also write a JSON sidecar for consumers expecting structured data
    sidecar = output_file.with_suffix(".json")
    sidecar.write_text(json.dumps(desc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # and a shell script sidecar
    sh = output_file.with_suffix(".sh")
    sh.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{command_text}", encoding="utf-8")

    return output_file


# Backwards/alternate names
render_seed = render_seed_command
render = render_seed_command
render_seed_file = render_seed_command
build_seed = render_seed_command
create_seed = render_seed_command
make_seed = render_seed_command
seed_command = render_seed_command
generate_seed_command = render_seed_command
render_deterministic_seed = render_seed_command


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", "--manifest-path", dest="manifest", type=Path,
                        default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--out", "--output", dest="out", type=Path, default=None)
    parser.add_argument("--ceiling", type=float, default=SPECTRAL_CEILING_HZ)
    args = parser.parse_args(argv)
    path = render_seed_command(args.manifest, out=args.out, ceiling_hz=args.ceiling)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
