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
    lower-cased, is one of ``true``, ``on``, ``1`` or ``yes``; an explicit
    ``false`` (or a hidden companion) is false.  An absent field falls
    back to the field's own default for every field kind.  Multi-choice
    checkboxes are joined with commas.
    """
    values = _form_values(form, field.name)
    if not values:
        if field.kind == "bool":
            return "true" if field.default else "false"
        if field.kind == "multichoice":
            if field.default:
                return ",".join(str(v) for v in field.default)
            return ""
        if field.default is None:
            return ""
        return str(field.default)

    last = values[-1]
    if field.kind == "bool":
        if last.strip().lower() in {"true", "on", "1", "yes"}:
            return "true"
        return "false"

    if field.kind == "multichoice":
        return ",".join(values)

    return last


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
