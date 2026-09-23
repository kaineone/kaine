# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Detect metadata-only incoherence in the PyTorch wheel stack.

The transformers error ``operator torchvision::nms does not exist`` happens
when a CUDA-tagged ``torch`` is paired with a different torchvision build
(e.g. torch 2.14.0+cu130 + torchvision 0.26.0+cu128). This module reads
distribution metadata to catch mismatched pins and mixed index builds before
the runtime imports any torch package.

The build version (including local tags such as ``+cu130``) is read from each
package's own ``version.py`` file because pip-installed dist-info metadata can
omit the build tag.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, distribution

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

_ORDER = ("torch", "torchvision", "torchaudio")

_VERSION_RE = re.compile(
    r'^__version__\s*(?::\s*[^\n=]+?)?\s*=\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)


def _load_metadata() -> dict[str, tuple[str, list[str]]]:
    """Read version and Requires-Dist for the torch stack from importlib.metadata.

    The version string is taken from each package's ``<name>/version.py`` file
    when available, since ``dist.version`` may drop the local build tag. If
    that file is missing, unreadable, or does not contain a parsable
    ``__version__`` assignment, ``dist.version`` is used as a fallback.
    """
    dists: dict[str, tuple[str, list[str]]] = {}
    for name in _ORDER:
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue
        version = dist.version
        try:
            version_file = dist.locate_file(f"{name}/version.py")
            if version_file is not None:
                text = version_file.read_text(encoding="utf-8")
                match = _VERSION_RE.search(text)
                if match:
                    version = match.group(1)
        except Exception:
            # Best-effort read of <pkg>/version.py; any failure falls back to
            # dist.version so the coherence check never raises.
            pass
        reqs = dist.requires or []
        dists[name] = (version, list(reqs))
    return dists


def _parse_version(raw: str, label: str, problems: list[str]) -> Version | None:
    try:
        return Version(raw)
    except InvalidVersion as exc:
        problems.append(f"{label} version {raw!r} could not be parsed: {exc}")
        return None


def _torch_pin(requirement: str, label: str, problems: list[str]) -> str | None:
    """Return the == pin for a torch requirement, or None if not applicable."""
    if not requirement.lower().startswith("torch"):
        return None
    try:
        req = Requirement(requirement)
    except Exception as exc:  # packaging can raise several exception types
        problems.append(f"{label} has unparseable Requires-Dist {requirement!r}: {exc}")
        return None
    if req.name.lower() != "torch":
        return None
    if req.marker and "extra" in str(req.marker).lower():
        return None
    for spec in req.specifier:
        if spec.operator == "==":
            return spec.version
    return None


def check_torch_stack(
    dists: Mapping[str, tuple[str, list[str]]] | None = None,
) -> list[str]:
    """Return human-readable problems for the installed torch stack.

    An empty list means the stack is coherent according to the metadata.
    """
    problems: list[str] = []
    if dists is None:
        dists = _load_metadata()

    if "torch" not in dists:
        # Nothing to anchor the check.
        return problems

    parsed: dict[str, tuple[str, Version, str | None]] = {}
    for name in _ORDER:
        if name not in dists:
            continue
        raw = dists[name][0]
        version = _parse_version(raw, name, problems)
        if version is None:
            continue
        tag = str(version.local) if version.local else None
        parsed[name] = (raw, version, tag)

    if "torch" not in parsed:
        # The torch version string itself was unparseable; problems already recorded.
        return problems

    torch_raw, torch_version, _ = parsed["torch"]

    for name in ("torchvision", "torchaudio"):
        if name not in parsed:
            continue
        raw = dists[name][0]
        pin: str | None = None
        for req in dists[name][1]:
            found = _torch_pin(req, name, problems)
            if found is not None:
                pin = found
                break
        if pin is None:
            continue
        try:
            pin_version = Version(pin)
        except InvalidVersion as exc:
            problems.append(
                f"{name} requires torch=={pin!r} but that version could not be parsed: {exc}"
            )
            continue
        if torch_version.base_version != pin_version.base_version:
            problems.append(
                f"{name} {raw} requires torch=={pin} but torch {torch_raw} is installed"
            )

    tags = {tag for _, _, tag in parsed.values()}
    if len(tags) > 1:
        members = ", ".join(f"{name} {parsed[name][0]}" for name in _ORDER if name in parsed)
        problems.append(
            f"mixed builds: {members} (all torch-stack wheels must come from the same index)"
        )

    return problems


def describe_torch_stack(
    dists: Mapping[str, tuple[str, list[str]]] | None = None,
) -> str:
    """Return a short description of the installed torch stack."""
    if dists is None:
        dists = _load_metadata()
    if "torch" not in dists:
        return "torch not installed"
    return ", ".join(
        f"{name} {dists[name][0]}" for name in _ORDER if name in dists
    )
