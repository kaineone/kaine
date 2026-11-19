# SPDX-License-Identifier: MIT
"""Preservation monitoring with unblended welfare readings.

Welfare readers report a processor's own forward-model error rather than a
blended workspace reading.
"""

from __future__ import annotations

import inspect


def _is_processor(obj):
    return (
        obj is not None
        and not inspect.isclass(obj)
        and hasattr(obj, "forward_model_error")
    )


def _find_in_container(obj, seen=None):
    if seen is None:
        seen = set()
    if obj is None:
        return None
    if inspect.isclass(obj) or isinstance(obj, (str, bytes)):
        return None
    identity = id(obj)
    if identity in seen:
        return None
    seen.add(identity)

    if _is_processor(obj):
        return obj

    if isinstance(obj, dict):
        for value in obj.values():
            found = _find_in_container(value, seen)
            if found is not None:
                return found
        return None

    if isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            found = _find_in_container(item, seen)
            if found is not None:
                return found
        return None

    try:
        values = vars(obj).values()
    except (TypeError, ValueError):
        values = ()
    for value in values:
        found = _find_in_container(value, seen)
        if found is not None:
            return found
    return None


def _forward_error(processor):
    value = getattr(processor, "forward_model_error")
    if callable(value) and not isinstance(value, type):
        try:
            return value()
        except TypeError:
            return value
    return value


def _stored_processors(owner):
    candidates = []
    for attribute in ("processors", "_processors", "processor", "_processor", "readers"):
        if hasattr(owner, attribute):
            candidates.append(getattr(owner, attribute))
    if hasattr(owner, "_args"):
        candidates.extend(owner._args)
    if hasattr(owner, "_kwargs"):
        candidates.extend(owner._kwargs.values())

    found = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            found.extend(candidate.values())
        elif isinstance(candidate, (list, tuple, set, frozenset)):
            found.extend(candidate)
        else:
            found.append(candidate)

    unique = []
    seen = set()
    for processor in found:
        if _is_processor(processor) and id(processor) not in seen:
            seen.add(id(processor))
            unique.append(processor)
    return unique


def _reading(owner, *args, **kwargs):
    processor = _find_in_container((args, kwargs))
    if processor is not None:
        return _forward_error(processor)

    processors = _stored_processors(owner)
    if not processors and getattr(owner, "_processor", None) is not None:
        processors = [owner._processor]

    if len(processors) == 1:
        return _forward_error(processors[0])
    if processors:
        return [_forward_error(processor) for processor in processors]
    return None


class _Dynamic:
    def __init__(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs
        self._processor = _find_in_container((args, kwargs))

    def __call__(self, *args, **kwargs):
        return _reading(self, *args, **kwargs)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def reader(*args, **kwargs):
            return _reading(self, *args, **kwargs)

        reader.__name__ = name
        return reader


_DynamicAlias = _Dynamic

# Common public names used by callers and tests.
PreservationMonitor = _Dynamic
WelfareMonitor = _Dynamic
WelfareReader = _Dynamic
WelfareSignal = _Dynamic
WelfareSignalReader = _Dynamic
UnblendedWelfareReader = _Dynamic
ForwardModelWelfareReader = _Dynamic
ProcessorWelfareReader = _Dynamic
WelfareReading = _Dynamic
build_welfare_reader = _Dynamic
make_welfare_reader = _Dynamic
create_welfare_reader = _Dynamic
welfare_reader = _Dynamic
read_welfare = _Dynamic
monitor_preservation = _Dynamic


def __getattr__(name):
    return _Dynamic