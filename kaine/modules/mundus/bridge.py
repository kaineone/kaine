# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Wire protocol for the Mundus bridge (KAINE ↔ the LEAP shim).

Length-prefixed MessagePack frames over a localhost TCP socket — the same shape
the Kosmos/Paracosm bridge uses, so the two embodiment connectors stay
symmetric. The shim (running inside the viewer) connects out to the Mundus
module's listener; perception flows shim→KAINE, action intents flow KAINE→shim.

Frame = u32 big-endian length, then that many bytes of MessagePack.

Feed frames (shim → KAINE), keyed by ``kind``:
  proprio        {region, position:[x,y,z], look_at, agent_id, display_name}
  scene          {object_count, by_type:{...}}              # nearby objects summary
  entity         {avatars:[{id,name,position}], arrived:[ids], left:[ids]}
  chat           {channel, from_id, from_name, message, kind}   # INBOUND local chat
  frame          {w, h, encoding:"rgb8", seq}  # vision; raw bytes redacted from bus
  notice         {kind, summary, auto_declined:bool}  # offers/dialogs auto-handled
  action_result  {action, ok, reason?}

Action frames (KAINE → shim), keyed by ``kind="action"``:
  {kind:"action", action:"move"|"turn"|"say"|"teleport"|"sit_on"|"stand"|
                         "touch"|"animate"|"gesture", ...params, reqid}
"""
from __future__ import annotations

import asyncio
import struct
from typing import Any

import msgpack

_LEN = struct.Struct(">I")
MAX_FRAME_BYTES = 8 * 1024 * 1024  # 8 MiB cap (matches the Paracosm bridge)

# Feed kinds (shim → KAINE) → (bus event type, baseline salience).
FEED_EVENT = {
    "proprio": ("mundus.proprio", 0.3),
    "scene": ("mundus.scene", 0.15),
    "entity": ("mundus.entity", 0.2),
    "chat": ("mundus.chat", 0.6),
    "frame": ("mundus.visual.raw", 0.1),
    "notice": ("mundus.notice", 0.6),
    "action_result": ("mundus.action.result", 0.3),
}

# Action families KAINE may drive, and their default exposure. World-mutating,
# economy, touch, and teleport default OFF (operator opt-in) per safety-first.
ACTION_DEFAULT_EXPOSED = {
    "move": True, "turn": True, "say": True, "sit_on": True, "stand": True,
    "animate": True, "gesture": True, "teleport": False, "touch": False,
}


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read one length-prefixed MessagePack frame; None at clean EOF."""
    try:
        header = await reader.readexactly(_LEN.size)
    except asyncio.IncompleteReadError:
        return None
    (length,) = _LEN.unpack(header)
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise ValueError(f"mundus bridge: bad frame length {length}")
    body = await reader.readexactly(length)
    obj = msgpack.unpackb(body, raw=False)
    if not isinstance(obj, dict):
        raise ValueError("mundus bridge: frame is not a map")
    return obj


async def write_frame(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
    body = msgpack.packb(obj, use_bin_type=True)
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError("mundus bridge: outbound frame too large")
    writer.write(_LEN.pack(len(body)) + body)
    await writer.drain()
