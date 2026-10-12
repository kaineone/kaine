# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Translate config keys into constructor keyword arguments during boot."""
from __future__ import annotations

import inspect
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import Any

from kaine import legacy_names


def parameter_for_config_key(key: str, parameters: Collection[str]) -> str:
    """The constructor parameter that config ``key`` feeds.

    ``key`` itself when the constructor accepts it. Otherwise the key with every
    underscore-separated component that is an old module key (a key of
    ``legacy_names.MODULES``) replaced by that module's ``new_key``, when the
    constructor accepts that name. Otherwise ``key`` unchanged (the constructor
    then reports it). Once the config keys are renamed too, the first rule applies
    and the map is the identity.
    """
    if key in parameters:
        return key

    parts = key.split("_")
    max_old_len = max((len(name.split("_")) for name in legacy_names.MODULES), default=1)

    mapped_parts: list[str] = []
    i = 0
    n = len(parts)
    while i < n:
        for length in range(min(max_old_len, n - i), 0, -1):
            run = "_".join(parts[i : i + length])
            entry = legacy_names.MODULES.get(run)
            if entry is not None:
                mapped_parts.append(entry["new_key"])
                i += length
                break
        else:
            mapped_parts.append(parts[i])
            i += 1

    mapped = "_".join(mapped_parts)
    return mapped if mapped in parameters else key


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
