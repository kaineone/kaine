# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Translate config keys into constructor keyword arguments during boot."""
from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from kaine.legacy_aliases import parameter_for_config_key

__all__ = ["config_kwargs", "parameter_for_config_key"]


def config_kwargs(
    section: Mapping[str, Any],
    keys: Iterable[str],
    target: Callable[..., Any],
    *,
    convert: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Copy ``keys`` present in ``section`` into keyword arguments for ``target``.

    Each key is mapped through :func:`parameter_for_config_key` against the
    parameters of ``target`` (``inspect.signature(target).parameters``; for a class,
    its ``__init__``). ``convert``, when given, is applied to each value.
    """
    try:
        param_names = set(inspect.signature(target).parameters)
    except ValueError:
        param_names = set()

    result: dict[str, Any] = {}
    for key in keys:
        if key not in section:
            continue
        param = parameter_for_config_key(key, param_names)
        value = section[key]
        if convert is not None:
            value = convert(value)
        result[param] = value
    return result
