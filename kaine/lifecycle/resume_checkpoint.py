# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Rolling resume checkpoint for module state.

This module keeps one rolling checkpoint of every module's serialize() output in the state tree
and restores it on a plain start. Per paper A.7, module state persists with the entity,
checkpointed each entity minute and at shutdown, so a restart neither resets nor repeats it.
The checkpoint is one file that is replaced atomically and encrypted through the process state encryptor.
A revive never reads this checkpoint.
Module state is checkpointed only while awake. A developmental state-cycle rest is the one
exception, and it touches only the sleep module's state_cycle entry inside the last awake
checkpoint (phase and rest time spent), so a process restart resumes the rest for its remainder
while no other module's entry ever holds possibly inconsistent mid-sleep state.

Self-persisting modules (self_model, episodic_memory, social_cognition, world_model) are excluded
because they keep their own store or file that they reload on start; capturing them would risk rolling
that store back. Transient bus stream cursors are excluded because restoring an old cursor would make
a module replay events it already handled.
Some fields of a self-persisting module are not held in its own file, so the checkpoint carries
them instead; for example, it carries the self_model drift_count.
A module whose serialize() raises or returns a non-dict is omitted from that checkpoint and
starts fresh on a plain restart; the omission is recorded in metadata.
After a revive, any checkpoint written before the revive is ignored so old pre-revive state is
not restored; this guard uses a small revive record file.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import os
import time
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

ASIDE_FILENAME = CHECKPOINT_FILENAME + ".pre-revive"
REVIVE_RECORD_FILENAME = "revive.json"

# Modules that manage their own persistent store. Capturing them would roll their store back.
SELF_PERSISTING_MODULES = frozenset({"self_model", "episodic_memory", "social_cognition", "world_model"})

# Fields of a self-persisting module that its own file does not hold, so the checkpoint carries them.
CARRIED_FIELDS = {"self_model": ("drift_count",)}

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
        # chmod is best effort on filesystems without POSIX modes.
        pass


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory so a rename on top of it is durable."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        os.fsync(fd)
    except OSError:
        # Directory fsync is best effort; not every platform supports it.
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                # The descriptor is unusable either way; there is nothing left to release.
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
    omitted: list[str] = []

    for module in registry.all_modules():
        name = module.name
        if name in SELF_PERSISTING_MODULES and name not in CARRIED_FIELDS:
            continue

        try:
            raw_state = module.serialize()
        except Exception as exc:
            type_name = type(exc).__name__
            log.warning(
                "resume checkpoint: module %s omitted from this checkpoint (%s); it starts fresh on a plain restart",
                name,
                type_name,
            )
            omitted.append(name)
            continue

        if not isinstance(raw_state, dict):
            type_name = type(raw_state).__name__
            log.warning(
                "resume checkpoint: module %s omitted from this checkpoint (%s); it starts fresh on a plain restart",
                name,
                type_name,
            )
            omitted.append(name)
            continue

        state = copy.deepcopy(raw_state)
        for key in TRANSIENT_KEYS.get(name, ()):
            state.pop(key, None)

        if name in CARRIED_FIELDS:
            state = {k: state[k] for k in CARRIED_FIELDS[name] if k in state}

        modules[name] = state

    metadata = {
        "kind": CHECKPOINT_KIND,
        "version": CHECKPOINT_VERSION,
        "reason": reason,
        "identity": identity.to_dict(),
        "awake_seconds": awake_seconds,
        "excluded_modules": sorted(SELF_PERSISTING_MODULES),
        "omitted_modules": sorted(omitted),
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
                    # The descriptor is unusable either way; there is nothing left to release.
                    pass
        _chmod_best_effort(tmp, 0o600)
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            # Removing the temp file is best effort; the original error is re-raised below.
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


def set_aside_for_revive(directory: Path | None = None, *, revived_from: str | None = None) -> bool:
    """Record that a revive has started and move the current checkpoint out of the way."""
    target = checkpoint_file(directory)
    directory = target.parent
    record = directory / REVIVE_RECORD_FILENAME
    aside = target.with_name(ASIDE_FILENAME)

    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _chmod_best_effort(directory, 0o700)

        payload = json.dumps(
            {"started_at": time.time(), "revived_from": revived_from},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        tmp = directory / (REVIVE_RECORD_FILENAME + ".tmp")
        fd: int | None = None
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        # The descriptor is unusable either way; there is nothing left to release.
                        pass
            _chmod_best_effort(tmp, 0o600)
            os.replace(tmp, record)
            _fsync_dir(directory)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                # Removing the temp file is best effort; the original error is re-raised below.
                pass
            raise

        if target.is_file():
            os.replace(target, aside)
            log.info(
                "resume checkpoint: set checkpoint aside at %s for revive (from %s)",
                aside,
                revived_from,
            )
        else:
            log.info(
                "resume checkpoint: no checkpoint to set aside for revive (from %s)",
                revived_from,
            )

        leftover_tmp = target.with_name(CHECKPOINT_FILENAME + ".tmp")
        if leftover_tmp.is_file():
            leftover_tmp.unlink()

        return True
    except Exception as exc:
        log.error(
            "resume checkpoint: could not set the checkpoint aside before a revive: %s",
            type(exc).__name__,
        )
        return False


def read_revive_started_at(directory: Path | None = None) -> float | None:
    """Return the started_at timestamp from the revive record, or None."""
    record = checkpoint_file(directory).parent / REVIVE_RECORD_FILENAME
    if not record.is_file():
        return None

    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        started = data.get("started_at")

        if isinstance(started, bool) or not isinstance(started, (int, float)):
            return None

        started = float(started)
        if not math.isfinite(started):
            return None

        return started
    except Exception as exc:
        log.debug("resume checkpoint: revive record not readable: %s", type(exc).__name__)
        return None


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

    started = read_revive_started_at(directory)
    if started is not None and snap.timestamp < started:
        log.warning(
            "resume checkpoint: ignoring checkpoint %s written before the latest revive; modules start fresh",
            path,
        )
        return None

    by_name = {module.name: module for module in registry.all_modules()}
    restored: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for name in sorted(snap.modules):
        if name in SELF_PERSISTING_MODULES and name not in CARRIED_FIELDS:
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

        if name in CARRIED_FIELDS:
            state = {k: state[k] for k in CARRIED_FIELDS[name] if k in state}

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


def _rest_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a sleep state_cycle entry; an awake entry always carries awake_s 0."""
    phase = entry.get("phase")
    spent = entry.get("rest_spent_s")
    if phase == "resting":
        if isinstance(spent, bool) or not isinstance(spent, (int, float)) or not math.isfinite(spent) or spent < 0:
            return None
        return {"phase": "resting", "awake_s": 0.0, "rest_spent_s": float(spent)}
    if phase == "awake":
        return {"phase": "awake", "awake_s": 0.0, "rest_spent_s": 0.0}
    return None


def update_state_cycle_entry(
    identity: EntityIdentity | None,
    entry: dict[str, Any],
    directory: Path | None = None,
) -> bool:
    """Replace only the sleep module's state_cycle entry inside the existing checkpoint.

    Every other module's entry stays as the last awake write left it. The same entity check
    and revive-record rule as a restore apply, and the write is the same atomic encrypted
    replace. With no usable checkpoint nothing is written.
    """
    new_entry = _rest_entry(entry)
    if new_entry is None or identity is None:
        return False

    try:
        snap = read_checkpoint(directory)
    except CheckpointUnreadable as exc:
        log.warning("resume checkpoint: rest progress not written, checkpoint unreadable (%s)", exc)
        return False
    if snap is None:
        log.debug("resume checkpoint: no checkpoint yet; rest progress not written")
        return False

    try:
        checkpoint_identity = identity_of_snapshot(snap)
    except Exception as exc:
        log.warning("resume checkpoint: rest progress not written (%s)", type(exc).__name__)
        return False
    if checkpoint_identity is None or checkpoint_identity.entity_id != identity.entity_id:
        log.warning("resume checkpoint: rest progress not written, the checkpoint is of another entity")
        return False

    started = read_revive_started_at(directory)
    if started is not None and snap.timestamp < started:
        log.warning("resume checkpoint: rest progress not written, the checkpoint predates the latest revive")
        return False

    sleep_state = snap.modules.get("sleep")
    if not isinstance(sleep_state, dict):
        log.debug("resume checkpoint: no sleep entry in the checkpoint; rest progress not written")
        return False

    sleep_state["state_cycle"] = new_entry
    try:
        write_checkpoint(snap, directory)
    except Exception as exc:
        log.warning("resume checkpoint: rest progress not written (%s); the previous one is kept", type(exc).__name__)
        return False
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
        rest_source: Callable[[], dict[str, Any] | None] | None = None,
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
        # Returns the sleep module's state_cycle entry, or None without one.
        self._rest_source = rest_source
        # Whether the checkpoint holds a resting entry this writer put there.
        self._rest_marked = False
        self._rest_written_spent = 0.0
        self._rest_retry_at = 0.0

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

    def _read_rest(self) -> dict[str, Any] | None:
        if self._rest_source is None:
            return None
        try:
            entry = self._rest_source()
        except Exception:
            return None
        return entry if isinstance(entry, dict) else None

    async def _sync_rest(self, *, final: bool = False) -> None:
        """Keep the checkpoint's sleep state_cycle entry in step with a running rest.

        Writes when a rest starts, each interval of rest time, at shutdown, and once when the
        rest ends (the entry then reads awake with 0 s), so a crash after a rest resumes none.
        """
        entry = self._read_rest()
        if entry is None:
            return
        resting = entry.get("phase") == "resting"
        if not resting and not self._rest_marked:
            return
        spent = entry.get("rest_spent_s") if resting else 0.0
        if resting and not final and self._rest_marked:
            if not isinstance(spent, (int, float)) or spent - self._rest_written_spent < self._interval:
                return
        if not final and time.monotonic() < self._rest_retry_at:
            return
        ok = await asyncio.to_thread(update_state_cycle_entry, self._identity, entry, self._directory)
        if not ok:
            self._rest_retry_at = time.monotonic() + self._interval
            return
        self.writes += 1
        self._rest_marked = resting
        self._rest_written_spent = float(spent) if resting else 0.0

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
                # The poll interval elapsed; check below whether a write is due.
                pass

            await self._sync_rest()

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
                    self._rest_marked = False
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
                # Cancellation is how this task is expected to stop.
                pass
            except Exception as exc:
                log.warning(
                    "resume checkpoint: checkpointer task ended with %s",
                    type(exc).__name__,
                    exc_info=True,
                )

    async def write_final(self, *, can_write: Callable[[], bool]) -> bool:
        """Write a final checkpoint on shutdown, or keep the last one if not allowed."""
        await self.stop()

        try:
            ok = bool(can_write())
        except Exception:
            ok = False

        if not ok:
            log.info(
                "resume checkpoint: asleep or frozen at shutdown; keeping the last awake checkpoint"
            )
            # A state-cycle rest still records its progress in the sleep entry alone.
            await self._sync_rest(final=True)
            return False

        success = await save_checkpoint(
            self._registry,
            self._identity,
            reason="shutdown",
            directory=self._directory,
            awake_seconds=self._read_awake(),
        )
        if success:
            self.writes += 1
            self._rest_marked = False
        return success
