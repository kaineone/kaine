# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Web rendering/validation helpers for the declarative step model."""
from __future__ import annotations

from typing import Any

from kaine.setup.steps import Field, parse_answer


def _form_values(form: Any, name: str) -> list[str]:
    """Return every submitted value for ``name`` as strings."""
    if isinstance(form, dict):
        value = form.get(name)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]
    return [str(v) for v in form.getlist(name)]


def form_value(form: Any, field: Field) -> str:
    """Return the string answer for ``field`` from a submitted form.

    ``form`` is either a Starlette :class:`FormData` or the dict produced by
    ``_read_form``.  A bool is true only when the LAST submitted value,
    lower-cased, is one of ``true``, ``on``, ``1`` or ``yes``; an absent
    field or any other submitted value (including an explicit ``false``)
    is false.  Multi-choice checkboxes are joined with commas; everything
    else falls back to the field default when absent.
    """
    if field.kind == "bool":
        values = _form_values(form, field.name)
        if not values:
            return "false"
        last = values[-1].strip().lower()
        if last in {"true", "on", "1", "yes"}:
            return "true"
        return "false"

    if field.kind == "multichoice":
        items = _form_values(form, field.name)
        return ",".join(items)

    raw = form.get(field.name) if hasattr(form, "get") else None
    if isinstance(raw, list):
        raw = raw[-1] if raw else None
    if raw is None:
        return ""
    return str(raw)


def validate_fields(fields, form) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate ``fields`` against ``form``; return ``(answers, errors)``.

    ``errors`` maps field name to message.
    """
    answers: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for fld in fields:
        value, err = parse_answer(fld, form_value(form, fld))
        if err:
            errors[fld.name] = err
        answers[fld.name] = value
    return answers, errors


def validate_step(step, ctx, form) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate every field in ``step`` against ``form``."""
    return validate_fields(tuple(step.fields(ctx)), form)
