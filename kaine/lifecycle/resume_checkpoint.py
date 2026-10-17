# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Rolling resume checkpoint for module state.

This module keeps one rolling checkpoint of every module's serialize() output in the state tree
and restores it on a plain start. Per paper A.7, module state persists with the entity,
checkpointed each entity minute and at shutdown, so a restart neither resets nor repeats it.
The checkpoint is one file that is replaced atomically and encrypted through the process state encryptor.
A revive never reads this checkpoint.

Self-persisting modules (self_model, episodic_memory, social_cognition, world_model) are excluded
because they keep their own store or file that they reload on start; capturing them would risk rolling
that store back. Transient bus stream cursors are excluded because restoring an old cursor would make
a module replay events it already handled.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kaine.lifecycle import stage as _stage
from kaine.lifecycle.identity import EntityIdentity, identity_of_snapshot
from kaine.lifecycle.snapshot import ForkSnapshot
from kaine.security.crypto import get_state_encryptor
from kaine.storage import resolve

log = logging.getLogger(__name__)

CHECKPOINT_DIRNAME = "checkpoint"
CHECKPOINT_FILENAME = "checkpoint.json"
CHECKPOINT_KIND = "resume_checkpoint"
CHECKPOINT_VERSION = 1
CHECKPOINT_INTERVAL_SECONDS = 60.0

# Modules that manage their own persistent store. Capturing them would roll their store back.
SELF_PERSISTING_MODULES = frozenset({"self_model", "episodic_memory", "social_cognition", "world_model"})

# Bus stream cursors. Restoring old values would cause duplicate replays.
TRANSIENT_KEYS = {
    "interoception": ("cycle_cursor",),
    "embodiment": ("intent_cursor", "speech_cursor"),
    "sequence": ("user_input_cursors",),
}


class CheckpointError(RuntimeError):
    """A checkpoint could not be captured."""


class CheckpointUnreadable(RuntimeError):
    """A checkpoint file exists but could not be decoded or validated."""


def checkpoint_dir() -> Path:
    """Directory where the rolling checkpoint lives."""
    return resolve(_stage.STAGE_PATH).parent / CHECKPOINT_DIRNAME


def checkpoint_file(directory: Path | None = None) -> Path:
    """Full path to the checkpoint file, optionally inside a custom directory."""
    return (Path(directory) if directory is not None else checkpoint_dir()) / CHECKPOINT_FILENAME


def _chmod_best_effort(path: Path, mode: int) -> None:
    """chmod a path, ignoring platforms or filesystems that do not support it."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory so a rename on top of it is durable."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        os.fsync(fd)
    except OSError:
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def capture_checkpoint(
    registry: Any,
    identity: EntityIdentity,
    *,
    reason: str,
    awake_seconds: float | None = None,
) -> ForkSnapshot:
    """Capture the serialized state of every non-self-persisting module."""
    modules: dict[str, dict[str, Any]] = {}

    for module in registry.all_modules():
        if module.name in SELF_PERSISTING_MODULES:
            continue

        try:
            raw_state = module.serialize()
        except Exception as exc:
            raise CheckpointError(
                f"could not capture module {module.name}: {type(exc).__name__}"
            ) from exc

        if not isinstance(raw_state, dict):
            raise CheckpointError(
                f"could not capture module {module.name}: serialize returned {type(raw_state).__name__}, not dict"
            )

        state = copy.deepcopy(raw_state)
        for key in TRANSIENT_KEYS.get(module.name, ()):
            state.pop(key, None)

        modules[module.name] = state

    metadata = {
        "kind": CHECKPOINT_KIND,
        "version": CHECKPOINT_VERSION,
        "reason": reason,
        "identity": identity.to_dict(),
        "awake_seconds": awake_seconds,
        "excluded_modules": sorted(SELF_PERSISTING_MODULES),
    }

    return ForkSnapshot(label="resume-checkpoint", modules=modules, adapters=[], metadata=metadata)


def write_checkpoint(snap: ForkSnapshot, directory: Path | None = None) -> Path:
    """Write a snapshot to the checkpoint file atomically and encrypted."""
    target = checkpoint_file(directory)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_best_effort(target.parent, 0o700)

    payload = json.dumps(snap.to_dict(), sort_keys=True, separators=(",", ":"))
    text = get_state_encryptor().encrypt_text(payload)
    data = text.encode("utf-8")

    tmp = target.with_name(CHECKPOINT_FILENAME + ".tmp")
    fd: int | None = None

    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        _chmod_best_effort(tmp, 0o600)
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return target


def read_checkpoint(directory: Path | None = None) -> ForkSnapshot | None:
    """Read and decrypt a checkpoint, or return None when it is absent."""
    target = checkpoint_file(directory)
    if not target.is_file():
        return None

    try:
        raw = target.read_bytes()
        plaintext = get_state_encryptor().maybe_decrypt(raw)
        text = plaintext.decode("utf-8")
        data = json.loads(text)

        if not isinstance(data, dict):
            raise ValueError("checkpoint top-level value is not a dict")

        snap = ForkSnapshot.from_dict(data)

        if snap.metadata.get("kind") != CHECKPOINT_KIND:
            raise ValueError(
                f"checkpoint kind mismatch: {snap.metadata.get('kind')!r}"
            )
        if snap.metadata.get("version") != CHECKPOINT_VERSION:
            raise ValueError(
                f"checkpoint version mismatch: {snap.metadata.get('version')!r}"
            )

        return snap
    except Exception as exc:
        raise CheckpointUnreadable(
            f"could not read resume checkpoint: {type(exc).__name__}"
        ) from exc


@dataclass(frozen=True)
class RestoreResult:
    """Outcome of a plain-start restore."""

    restored: tuple[str, ...]
    skipped: tuple[str, ...]
    fresh: tuple[str, ...]
    failed: tuple[str, ...]
    reason: str | None
    awake_seconds: float | None


def restore_checkpoint(
    registry: Any,
    identity: EntityIdentity | None,
    directory: Path | None = None,
) -> RestoreResult | None:
    """Restore module state on a plain restart. Never touches identity or stage files."""
    path = checkpoint_file(directory)

    if not path.is_file():
        log.info("resume checkpoint: none at %s; modules start fresh", path)
        return None

    try:
        snap = read_checkpoint(directory)
    except CheckpointUnreadable as exc:
        log.warning(
            "resume checkpoint: ignoring unreadable checkpoint %s (%s); modules start fresh",
            path,
            exc,
        )
        return None

    try:
        checkpoint_identity = identity_of_snapshot(snap)
    except Exception as exc:
        log.warning(
            "resume checkpoint: ignoring unreadable checkpoint %s (%s); modules start fresh",
            path,
            type(exc).__name__,
        )
        return None

    if (
        identity is None
        or checkpoint_identity is None
        or identity.entity_id != checkpoint_identity.entity_id
    ):
        log.warning(
            "resume checkpoint: ignoring checkpoint of entity %s; this state tree is entity %s; modules start fresh",
            checkpoint_identity.entity_id if checkpoint_identity else None,
            identity.entity_id if identity else None,
        )
        return None

    by_name = {module.name: module for module in registry.all_modules()}
    restored: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for name in sorted(snap.modules):
        if name in SELF_PERSISTING_MODULES:
            continue

        if name not in by_name:
            skipped.append(name)
            log.info(
                "resume checkpoint: module %s is not enabled now; skipped", name
            )
            continue

        state = snap.modules[name]
        if not isinstance(state, dict):
            failed.append(name)
            log.warning(
                "resume checkpoint: restoring module %s failed (%s); it keeps the state it has",
                name,
                "state not a dict",
            )
            continue

        state_copy = copy.deepcopy(state)
        for key in TRANSIENT_KEYS.get(name, ()):
            state_copy.pop(key, None)

        try:
            by_name[name].deserialize(state_copy)
        except Exception as exc:
            failed.append(name)
            log.warning(
                "resume checkpoint: restoring module %s failed (%s); it keeps the state it has",
                name,
                type(exc).__name__,
            )
        else:
            restored.append(name)

    fresh = [
        name
        for name in sorted(by_name)
        if name not in snap.modules and name not in SELF_PERSISTING_MODULES
    ]
    for name in fresh:
        log.info(
            "resume checkpoint: module %s not in the checkpoint; starting fresh", name
        )

    log.info(
        "resume checkpoint: restored %d modules from %s (reason=%s)",
        len(restored),
        path,
        snap.metadata.get("reason"),
    )

    return RestoreResult(
        restored=tuple(sorted(restored)),
        skipped=tuple(sorted(skipped)),
        fresh=tuple(sorted(fresh)),
        failed=tuple(sorted(failed)),
        reason=snap.metadata.get("reason"),
        awake_seconds=snap.metadata.get("awake_seconds"),
    )


async def save_checkpoint(
    registry: Any,
    identity: EntityIdentity | None,
    *,
    reason: str,
    directory: Path | None = None,
    awake_seconds: float | None = None,
) -> bool:
    """Capture and write a checkpoint off the main event loop."""
    if identity is None:
        log.warning("resume checkpoint: no entity identity; not written")
        return False

    try:
        snap = capture_checkpoint(registry, identity, reason=reason, awake_seconds=awake_seconds)
    except CheckpointError as exc:
        log.warning("resume checkpoint: not written, the previous one is kept: %s", exc)
        return False

    try:
        path = await asyncio.to_thread(write_checkpoint, snap, directory)
    except Exception as exc:
        log.warning(
            "resume checkpoint: not written (%s); the previous one is kept",
            type(exc).__name__,
        )
        return False

    log.debug("resume checkpoint: written to %s", path)
    return True


def discard_checkpoint(directory: Path | None = None) -> bool:
    """Remove the checkpoint file and its temporary sibling."""
    file = checkpoint_file(directory)
    tmp = file.with_name(CHECKPOINT_FILENAME + ".tmp")

    try:
        tmp.unlink(missing_ok=True)
        file.unlink(missing_ok=True)
    except OSError as exc:
        log.error("resume checkpoint: could not discard checkpoint at %s: %s", file, exc)
        return False

    return not file.exists()


class ResumeCheckpointer:
    """Periodic writer that checkpoints module state each entity minute."""

    def __init__(
        self,
        registry: Any,
        identity: EntityIdentity | None,
        *,
        awake_seconds: Callable[[], float],
        can_write: Callable[[], bool],
        directory: Path | None = None,
        interval_seconds: float = CHECKPOINT_INTERVAL_SECONDS,
        poll_seconds: float = 1.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")

        self._registry = registry
        self._identity = identity
        self._awake_seconds = awake_seconds
        self._can_write = can_write
        self._directory = directory
        self._interval = interval_seconds
        self._poll = poll_seconds

        self._stopping: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self.writes: int = 0

    def start(self) -> asyncio.Task:
        """Start the background checkpointing task."""
        if self._stopping is None:
            self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self.run(), name="cycle.resume_checkpoint")
        return self._task

    def _read_awake(self) -> float | None:
        try:
            return float(self._awake_seconds())
        except Exception:
            return None

    def _read_can_write(self) -> bool:
        try:
            return bool(self._can_write())
        except Exception:
            return False

    async def run(self) -> None:
        """Poll until stopped and write a checkpoint each interval of awake time."""
        if self._stopping is None:
            self._stopping = asyncio.Event()

        last: float | None = self._read_awake()

        while True:
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._poll)
                break
            except asyncio.TimeoutError:
                pass

            awake = self._read_awake()
            ok = self._read_can_write()

            if awake is None or not ok:
                log.debug("resume checkpoint: poll read failed", exc_info=True)
                continue

            if last is None:
                last = awake
                continue

            if awake - last >= self._interval:
                success = await save_checkpoint(
                    self._registry,
                    self._identity,
                    reason="periodic",
                    directory=self._directory,
                    awake_seconds=awake,
                )
                if success:
                    self.writes += 1
                last = awake

    async def stop(self) -> None:
        """Signal the loop to exit and wait for the task to finish."""
        if self._stopping is None:
            self._stopping = asyncio.Event()
        self._stopping.set()

        if self._task is not None and not self._task.done():
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning(
                    "resume checkpoint: checkpointer task ended with %s",
                    type(exc).__name__,
                    exc_info=True,
                )

    async def write_final(self, *, asleep: bool) -> bool:
        """Write a final checkpoint on shutdown, or keep the last one if asleep."""
        await self.stop()

        if asleep:
            log.info(
                "resume checkpoint: shutdown while asleep; keeping the last awake checkpoint"
            )
            return False

        ok = await save_checkpoint(
            self._registry,
            self._identity,
            reason="shutdown",
            directory=self._directory,
            awake_seconds=self._read_awake(),
        )
        if ok:
            self.writes += 1
        return ok
