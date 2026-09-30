# SPDX-License-Identifier: LicenseRef-CAL-0.2
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


def read_manifest(volume: Path) -> dict | None:
    path = volume / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict):
        _warn_once(f"{volume}:not_dict", f"organ adapter manifest {path} is not a dict")
        return None

    file = data.get("file")
    sha = data.get("sha256")
    gen = data.get("generation")
    adapter_id = data.get("adapter_id")
    problems: list[str] = []
    if not isinstance(file, str) or not _ACTIVE_FILE_RE.match(file):
        problems.append("file must match ^active-\\d+\\.gguf$")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        problems.append("sha256 must be 64 hex digits")
    if not isinstance(gen, int) or gen < 1:
        problems.append("generation must be int >= 1")
    if not isinstance(adapter_id, str):
        problems.append("adapter_id must be a string")

    if problems:
        _warn_once(
            f"{volume}:invalid",
            f"organ adapter manifest {path} invalid: {', '.join(problems)}",
        )
        return None

    return data


def _prune_old_adapters(volume: Path, current_gen: int) -> None:
    keep_floor = current_gen - 1
    for f in volume.glob("active-*.gguf"):
        try:
            n = int(f.stem.split("-", 1)[1])
        except (ValueError, IndexError):
            continue
        if n < keep_floor:
            f.unlink(missing_ok=True)


def activate(adapter_path: Path, volume: Path) -> dict:
    source = adapter_path / "adapter.gguf"
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"adapter source {source} must be a regular file")

    volume.mkdir(parents=True, exist_ok=True)

    current = read_manifest(volume)
    gen = (current["generation"] if current else 0) + 1
    target = volume / f"active-{gen}.gguf"
    tmp = volume / f"active-{gen}.gguf.tmp"

    shutil.copyfile(source, tmp)
    os.replace(str(tmp), str(target))
    os.chmod(target, 0o644)

    sha = sha256_file(target)
    manifest = {
        "file": target.name,
        "sha256": sha,
        "generation": gen,
        "adapter_id": adapter_path.name,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }

    manifest_tmp = volume / "active.json.tmp"
    manifest_tmp.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    os.replace(str(manifest_tmp), str(volume / MANIFEST))
    os.chmod(volume / MANIFEST, 0o644)

    gen_tmp = volume / f"{GENERATION}.tmp"
    gen_tmp.write_text(str(gen), encoding="utf-8")
    os.replace(str(gen_tmp), str(volume / GENERATION))
    os.chmod(volume / GENERATION, 0o644)

    _prune_old_adapters(volume, gen)
    return manifest


async def _default_http_get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
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
                    if Path(entry["path"]).name == expected_file:
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
            log.info("lingua organ adapter active: %s", reason)
        else:
            log.info("lingua organ adapter not active: %s", reason)

    async def lora_field(self) -> list[dict] | None:
        from kaine.modules.hypnos.adapter_store import current_path

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
                if Path(entry["path"]).name == manifest["file"]:
                    self._maybe_log(True, f"organ loaded {manifest['file']}")
                    return [{"id": entry["id"], "scale": 1.0}]
            except (KeyError, TypeError, AttributeError):
                continue

        self._maybe_log(False, "organ has not loaded it yet")
        return None
