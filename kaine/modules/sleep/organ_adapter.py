# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from kaine.modules.sleep.entity_volume import (
    entity_subdir,
    is_entity_id,
    require_entity_id,
)

log = logging.getLogger(__name__)

MANIFEST = "active.json"
GENERATION = "generation"

_ACTIVE_FILE_RE = re.compile(r"^active-\d+\.gguf$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_WARNED: set[str] = set()

HttpGet = Callable[[str, dict[str, str]], Awaitable[tuple[int, Any]]]
Clock = Callable[[], float]


def _warn_once(key: str, message: str) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    log.warning(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_manifest(
    path: Path, data: object, key: str, *, entity_id: str | None
) -> dict | None:
    """Check a parsed manifest.

    ``entity_id`` is the owner an entity manifest must name; ``None`` means the
    volume-root manifest, which is either a pointer naming its entity or the
    earlier flat layout.
    """
    if not isinstance(data, dict):
        _warn_once(f"{key}:not_dict", f"organ adapter manifest {path} is not a dict")
        return None

    file = data.get("file")
    sha = data.get("sha256")
    gen = data.get("generation")
    adapter_id = data.get("adapter_id")
    owner = data.get("entity_id")
    problems: list[str] = []
    if entity_id is not None:
        # An entity's own manifest inside <volume>/<entity_id>/.
        if owner != entity_id:
            problems.append(f"entity_id must be {entity_id}")
        if not isinstance(file, str) or not _ACTIVE_FILE_RE.match(file):
            problems.append("file must match ^active-\\d+\\.gguf$")
    elif "entity_id" in data:
        # The volume-root pointer: file is <entity_id>/active-N.gguf.
        if not is_entity_id(owner):
            problems.append("entity_id is not an entity id")
        elif not isinstance(file, str) or not re.fullmatch(
            re.escape(str(owner)) + r"/active-\d+\.gguf", file
        ):
            problems.append("file must be <entity_id>/active-N.gguf")
    elif not isinstance(file, str) or not _ACTIVE_FILE_RE.match(file):
        # The earlier flat layout: the file sits beside the manifest.
        problems.append("file must match ^active-\\d+\\.gguf$")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        problems.append("sha256 must be 64 hex digits")
    if not isinstance(gen, int) or isinstance(gen, bool) or gen < 1:
        problems.append("generation must be int >= 1")
    if not isinstance(adapter_id, str):
        problems.append("adapter_id must be a string")

    if problems:
        _warn_once(
            f"{key}:invalid",
            f"organ adapter manifest {path} invalid: {', '.join(problems)}",
        )
        return None

    return data


def read_manifest(volume: Path) -> dict | None:
    """Read the volume-root manifest: a pointer to one entity's adapter, or the earlier flat layout."""
    path = volume / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _validate_manifest(path, data, str(volume), entity_id=None)


def read_entity_manifest(volume: Path, entity_id: str) -> dict | None:
    """Read ``<volume>/<entity_id>/active.json``, the entity's own adapter manifest."""
    sub = entity_subdir(volume, entity_id)
    path = sub / MANIFEST
    if path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _validate_manifest(path, data, str(sub), entity_id=entity_id)


def _read_volume_generation(volume: Path) -> int:
    """The volume-wide generation counter the organ launcher watches (0 when absent)."""
    try:
        gen = int((volume / GENERATION).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        gen = 0
    root = read_manifest(volume)
    if root is not None:
        gen = max(gen, int(root["generation"]))
    return max(gen, 0)


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.parent / f"{path.name}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))
    os.chmod(path, 0o600)


def names_file(loaded_path: object, file: str) -> bool:
    """True when the organ's loaded adapter path ends with a manifest's ``file``."""
    want = Path(file).parts
    got = Path(str(loaded_path)).parts
    return bool(want) and len(got) >= len(want) and got[-len(want):] == want


def _prune_old_adapters(volume: Path, current_gen: int) -> None:
    keep_floor = current_gen - 1
    for f in volume.glob("active-*.gguf"):
        try:
            n = int(f.stem.split("-", 1)[1])
        except (ValueError, IndexError):
            continue
        if n < keep_floor:
            f.unlink(missing_ok=True)


def activate(adapter_path: Path, volume: Path, entity_id: str) -> dict:
    """Promote an adapter into ``<volume>/<entity_id>/`` and point the organ at it.

    Writes ``<entity_id>/active-N.gguf`` and the entity's own
    ``<entity_id>/active.json`` first, then the volume-root pointer
    ``active.json``, and last the volume-wide ``generation`` counter the organ
    launcher watches, each atomically. ``N`` counts this entity's promotions;
    the volume counter counts every entity's. Returns the pointer. Refuses an
    ``entity_id`` that is not in the identity format, and an entity directory
    that is a symlink or resolves anywhere but directly under the volume.
    """
    source = adapter_path / "adapter.gguf"
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"adapter source {source} must be a regular file")

    eid = require_entity_id(entity_id)
    volume.mkdir(parents=True, exist_ok=True)
    sub = entity_subdir(volume, eid, create=True)

    current = read_entity_manifest(volume, eid)
    gen = (current["generation"] if current else 0) + 1
    target = sub / f"active-{gen}.gguf"
    tmp = sub / f"active-{gen}.gguf.tmp"

    shutil.copyfile(source, tmp)
    os.replace(str(tmp), str(target))
    os.chmod(target, 0o600)

    sha = sha256_file(target)
    activated_at = datetime.now(timezone.utc).isoformat()
    entity_manifest = {
        "entity_id": eid,
        "file": target.name,
        "sha256": sha,
        "generation": gen,
        "adapter_id": adapter_path.name,
        "activated_at": activated_at,
    }
    _write_atomic(sub / MANIFEST, json.dumps(entity_manifest, separators=(",", ":")))

    volume_gen = _read_volume_generation(volume) + 1
    pointer = {
        "entity_id": eid,
        "file": f"{eid}/{target.name}",
        "sha256": sha,
        "generation": volume_gen,
        "adapter_id": adapter_path.name,
        "activated_at": activated_at,
    }
    _write_atomic(volume / MANIFEST, json.dumps(pointer, separators=(",", ":")))
    _write_atomic(volume / GENERATION, str(volume_gen))

    _prune_old_adapters(sub, gen)
    return pointer


async def _default_http_get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.get(url, headers=headers)
        try:
            data = resp.json()
        except Exception:
            data = None
        return resp.status_code, data


async def wait_ready(
    organ_url: str,
    expected_file: str,
    *,
    api_key: str | None = None,
    timeout_s: float = 300.0,
    poll_s: float = 2.0,
    http_get: Optional[HttpGet] = None,
    sleep=asyncio.sleep,
    clock: Clock = time.monotonic,
) -> bool:
    getter = http_get or _default_http_get
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{organ_url}/lora-adapters"
    deadline = clock() + timeout_s

    while True:
        try:
            status, data = await getter(url, headers)
        except Exception:
            status, data = -1, None

        if status == 200 and isinstance(data, list):
            for entry in data:
                try:
                    if names_file(entry["path"], expected_file):
                        return True
                except (KeyError, TypeError):
                    continue

        if clock() >= deadline:
            return False

        await sleep(poll_s)


def organ_root_url(chat_url: str) -> str:
    url = chat_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url.rstrip("/")


class OrganAdapterResolver:
    def __init__(
        self,
        *,
        adapter_output_dir: Path,
        volume: Path,
        organ_url: str,
        api_key: str | None,
        http_get: Optional[HttpGet] = None,
        ttl_s: float = 30.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self.adapter_output_dir = adapter_output_dir
        self.volume = volume
        self.organ_url = organ_url
        self.api_key = api_key
        self._http_get = http_get or _default_http_get
        self.ttl_s = float(ttl_s)
        self._clock = clock
        self._sha_cache: dict[tuple[str, int, int], str] = {}
        self._lora_cache: Optional[tuple[float, Any]] = None
        self._last_state: Optional[tuple[bool, str]] = None

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _maybe_log(self, applied: bool, reason: str) -> None:
        state = (applied, reason)
        if self._last_state == state:
            return
        self._last_state = state
        if applied:
            log.info("language organ adapter active: %s", reason)
        else:
            log.info("language organ adapter not active: %s", reason)

    async def lora_field(self) -> list[dict] | None:
        from kaine.modules.sleep.adapter_store import current_path

        manifest = read_manifest(self.volume)
        if manifest is None:
            self._maybe_log(False, "no manifest")
            return None

        own = current_path(self.adapter_output_dir)
        if own is None:
            self._maybe_log(False, "not this entity's adapter (no own adapter)")
            return None

        own_file = own / "adapter.gguf"
        if not own_file.is_file():
            self._maybe_log(False, "not this entity's adapter (no own adapter)")
            return None

        try:
            stat = own_file.stat()
        except OSError:
            self._maybe_log(False, "not this entity's adapter (no own adapter)")
            return None

        key = (str(own_file.resolve()), stat.st_mtime_ns, stat.st_size)
        own_sha = self._sha_cache.get(key)
        if own_sha is None:
            own_sha = sha256_file(own_file)
            self._sha_cache[key] = own_sha

        if own_sha != manifest.get("sha256"):
            self._maybe_log(False, "not this entity's adapter (SHA mismatch)")
            return None

        now = self._clock()
        if self._lora_cache is None or now >= self._lora_cache[0]:
            try:
                status, data = await self._http_get(
                    f"{self.organ_url}/lora-adapters",
                    self._auth_headers(),
                )
            except Exception:
                self._lora_cache = (now + self.ttl_s, None)
                self._maybe_log(False, "organ has not loaded it yet (GET error)")
                return None

            if status != 200:
                self._lora_cache = (now + self.ttl_s, None)
                self._maybe_log(False, "organ has not loaded it yet (non-200)")
                return None

            self._lora_cache = (now + self.ttl_s, data)
        else:
            data = self._lora_cache[1]

        if not isinstance(data, list):
            self._maybe_log(False, "organ has not loaded it yet")
            return None

        for entry in data:
            try:
                if names_file(entry["path"], manifest["file"]):
                    self._maybe_log(True, f"organ loaded {manifest['file']}")
                    return [{"id": entry["id"], "scale": 1.0}]
            except (KeyError, TypeError, AttributeError):
                continue

        self._maybe_log(False, "organ has not loaded it yet")
        return None
