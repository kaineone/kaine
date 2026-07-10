# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The body-agnostic embodiment-adapter contract.

Mundus is a control plane that routes the entity's perception and action to and
from a *body* through a pluggable :class:`EmbodimentAdapter`. The core knows no
wire protocol, transport, or platform vocabulary; each body (a virtual world, a
VR runtime, a robot, another effector platform) is a small local adapter the
core drives through this one narrow interface plus a declared capability
descriptor.

An adapter:

* declares an :class:`EmbodimentCapabilities` descriptor — feed-kind → (bus
  event, baseline salience), symbolic action families with default exposure,
  continuous channels (if any), and the payload keys carrying raw sense buffers;
* owns its transport (opening/closing it in :meth:`open`/:meth:`close`);
* produces perception as :class:`FeedFrame` values from :meth:`feed`, and never
  publishes to the bus itself — so salience policy and zero-raw-persistence stay
  in one auditable place, the core;
* accepts action through :meth:`apply_action` (symbolic verbs) and/or
  :meth:`apply_setpoints` (continuous graded channels), implementing whichever
  its body supports and declaring that in its descriptor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Protocol, Tuple, runtime_checkable


@dataclass(frozen=True)
class FeedFrame:
    """One unit of perception from the body: a ``kind`` plus its metadata payload.

    The ``kind`` is mapped to a bus event and baseline salience by the adapter's
    descriptor; ``payload`` carries the metadata (with any raw-sense buffer keys
    stripped by the core before publish). ``kind`` is not part of the payload.
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbodimentCapabilities:
    """What a body can do — read by the core instead of being hardcoded.

    Fields:
      name: adapter identity, e.g. ``"stub"``.
      transitional: ``True`` marks a body expected to be retired (the seam's
        reference/conformance body rather than a long-lived one).
      feed_events: feed ``kind`` → (bus event type, baseline salience in [0,1]).
        The core maps each yielded feed frame's ``kind`` to this event and
        salience; a ``kind`` absent from this table is dropped.
      action_families: symbolic action family → default exposure. The core
        merges operator overrides on top of these defaults; the descriptor
        itself always carries defaults.
      continuous_channels: names of clamped continuous setpoint channels the body
        supports (empty for a symbolic-only body). Canonical vocabulary lives in
        the core (:data:`kaine.modules.mundus.module.CONTINUOUS_CHANNEL_RANGE`).
      raw_buffer_keys: payload keys naming raw sense buffers the core must strip
        before publishing, so no rendered frame buffer ever reaches bus or disk.
    """

    name: str
    transitional: bool
    feed_events: Mapping[str, Tuple[str, float]]
    action_families: Mapping[str, bool]
    continuous_channels: Tuple[str, ...] = ()
    raw_buffer_keys: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("EmbodimentCapabilities.name must be a non-empty string")
        for kind, mapping in self.feed_events.items():
            if not isinstance(kind, str) or not kind:
                raise ValueError("feed_events keys must be non-empty strings")
            if (
                not isinstance(mapping, tuple)
                or len(mapping) != 2
                or not isinstance(mapping[0], str)
                or not mapping[0]
            ):
                raise ValueError(
                    f"feed_events[{kind!r}] must be (event_type, salience)"
                )
            salience = mapping[1]
            if not isinstance(salience, (int, float)) or not (0.0 <= float(salience) <= 1.0):
                raise ValueError(
                    f"feed_events[{kind!r}] salience must be in [0, 1]"
                )
        for family, exposed in self.action_families.items():
            if not isinstance(family, str) or not family:
                raise ValueError("action_families keys must be non-empty strings")
            if not isinstance(exposed, bool):
                raise ValueError(
                    f"action_families[{family!r}] default exposure must be bool"
                )
        if len(set(self.continuous_channels)) != len(self.continuous_channels):
            raise ValueError("continuous_channels must not repeat a channel name")
        for channel in self.continuous_channels:
            if not isinstance(channel, str) or not channel:
                raise ValueError("continuous_channels names must be non-empty strings")
        for key in self.raw_buffer_keys:
            if not isinstance(key, str) or not key:
                raise ValueError("raw_buffer_keys must be non-empty strings")


@runtime_checkable
class EmbodimentAdapter(Protocol):
    """The one narrow interface the Mundus core drives a body through."""

    def capabilities(self) -> EmbodimentCapabilities:
        """Return the (immutable) capability descriptor for this body."""
        ...

    async def open(self) -> None:
        """Bind the socket / connect / spawn the transport for this body."""
        ...

    async def close(self) -> None:
        """Tear the transport down; idempotent."""
        ...

    def feed(self) -> AsyncIterator[FeedFrame]:
        """Yield perception frames (body → core) until the body disconnects."""
        ...

    async def apply_action(self, family: str, params: dict[str, Any]) -> bool:
        """Symbolic sink: perform action ``family`` with ``params``; True on send."""
        ...

    async def apply_setpoints(self, channels: dict[str, float]) -> bool:
        """Continuous sink: drive graded ``channels``; True on send.

        A body with no continuous channels returns ``False`` (unsupported).
        """
        ...
