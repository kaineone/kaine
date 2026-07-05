# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.templates import (
    DEFAULT_EMPTY_SNAPSHOT_TEXT,
    TEMPLATES,
    fallback_template,
)


class FaithfulRenderer:
    """Deterministic plain-text renderer for bus events and snapshots.

    The renderer is a pure function: identical inputs produce identical
    outputs. The only state is the templates registry (immutable at use
    time).
    """

    def __init__(
        self,
        *,
        templates=None,
        empty_snapshot_text: str = DEFAULT_EMPTY_SNAPSHOT_TEXT,
        line_prefix: str = "- ",
    ) -> None:
        self._templates = dict(templates) if templates is not None else dict(TEMPLATES)
        self._empty_snapshot_text = empty_snapshot_text
        self._line_prefix = line_prefix

    def render_event(self, event: Event) -> str:
        key = (event.source, event.type)
        template = self._templates.get(key)
        if template is None:
            return fallback_template(event.source, event.type, dict(event.payload))
        return template(dict(event.payload))

    def render_snapshot(self, snapshot: WorkspaceSnapshot) -> str:
        events = snapshot.selected_events or []
        if not events:
            return self._empty_snapshot_text
        lines = [self._line_prefix + self.render_event(ev) for _, ev in events]
        return "\n".join(lines)

    def render_snapshot_bounded(
        self,
        snapshot: WorkspaceSnapshot,
        *,
        max_events: int = 8,
        char_budget: int = 2000,
    ) -> str:
        """Render at most ``max_events`` selected events, chosen by highest
        salience and capped at ``char_budget`` characters, then ordered stably
        (by original coalition order) for readability. Feeds the conscious
        workspace into Lingua's prompt without unbounded growth;
        ``render_snapshot`` is unchanged for existing callers.

        At-least-one policy: the single highest-salience event is always
        included even if it alone exceeds ``char_budget`` (so a non-empty
        coalition never renders to nothing); each subsequent event is dropped
        when adding it would exceed the budget. ``max_events <= 0`` renders
        nothing.
        """
        events = snapshot.selected_events or []
        if not events:
            return self._empty_snapshot_text
        scores = snapshot.salience_scores or {}
        indexed = list(enumerate(events))  # (orig_idx, (entry_id, event))
        # Rank by salience desc; ties keep original coalition order (stable).
        ranked = sorted(
            indexed,
            key=lambda t: (-(scores.get(t[1][0], 0.0)), t[0]),
        )
        survivors: list[tuple[int, str]] = []  # (orig_idx, rendered_line)
        total = 0
        for orig_idx, (_entry_id, event) in ranked[: max(0, max_events)]:
            line = self._line_prefix + self.render_event(event)
            cost = len(line) + (1 if survivors else 0)  # +1 newline after the first
            if survivors and total + cost > char_budget:
                break  # over budget; lower-salience remaining are dropped
            survivors.append((orig_idx, line))
            total += cost
        if not survivors:
            return self._empty_snapshot_text
        survivors.sort(key=lambda t: t[0])  # restore readable (coalition) order
        return "\n".join(line for _, line in survivors)
