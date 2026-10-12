# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""
Runtime alias readers for Kaine's legacy module names.

Each reader maps an old name to its new name only for codemod scopes that are
marked ``done`` in :mod:`kaine.legacy_names`. Pending scopes leave the reader
inert: old names are still current.
"""

import argparse
import copy
import json
import logging
import os
from collections.abc import Iterable
from typing import Any

from kaine import legacy_names

log = logging.getLogger("kaine.legacy")

_env_warnings_seen: set[str] = set()
_record_warnings_seen: set[tuple[str, str]] = set()


def _table() -> Any:
    """Return the live ``kaine.legacy_names`` module so tests can monkeypatch it."""
    return legacy_names


class LegacyNameConflict(ValueError):
    """An old and a new name are both set for the same item."""


def scope_done(scope: str) -> bool:
    """Return True when a rename scope is complete."""
    return _table().SCOPE_STATUS.get(scope) == "done"


def active(entries: Iterable[dict]) -> list[dict]:
    """Return the entries whose scope is marked done."""
    return [entry for entry in entries if scope_done(entry["scope"])]


def _split_path(path: str) -> list[str]:
    """Split a dotted config path into segments."""
    return path.split(".")


def _path_exists(data: dict, segments: list[str]) -> bool:
    """Check whether ``segments`` exists in the nested ``data`` mapping."""
    node = data
    for segment in segments:
        if not isinstance(node, dict) or segment not in node:
            return False
        node = node[segment]
    return True


def _path_get(data: dict, segments: list[str]) -> Any:
    """Return the value at ``segments``; assumes it exists."""
    node = data
    for segment in segments:
        node = node[segment]
    return node


def _path_set(data: dict, segments: list[str], value: Any) -> None:
    """Create intermediate tables as needed and set ``value`` at ``segments``."""
    node = data
    for segment in segments[:-1]:
        if not isinstance(node.get(segment), dict):
            node[segment] = {}
        node = node[segment]
    node[segments[-1]] = value


def _path_delete_and_clean(data: dict, segments: list[str]) -> None:
    """Delete a path and remove any parent tables that become empty."""
    if not segments:
        return
    parents: list[tuple[dict, str]] = []
    node = data
    for segment in segments:
        if not isinstance(node, dict) or segment not in node:
            return
        parents.append((node, segment))
        node = node[segment]
    parent, leaf = parents[-1]
    del parent[leaf]
    for parent, segment in reversed(parents[:-1]):
        if isinstance(parent.get(segment), dict) and not parent[segment]:
            del parent[segment]
        else:
            break


def _walk_tables(
    data: dict,
    path: tuple[str, ...] = (),
) -> Iterable[tuple[tuple[str, ...], dict]]:
    """Yield every table (nested dict) and its dotted path."""
    yield path, data
    for key, value in data.items():
        if isinstance(value, dict):
            yield from _walk_tables(value, path + (key,))


def _format_table_path(path: tuple[str, ...]) -> str:
    """Format a table path for messages."""
    return ".".join(path)


def _warn_record_both(old_key: str, new_key: str) -> None:
    """Warn once per process that a record contains both old and new names."""
    pair = (old_key, new_key)
    if pair not in _record_warnings_seen:
        _record_warnings_seen.add(pair)
        log.warning(
            "records: %s and %s are both present; keeping %s",
            old_key,
            new_key,
            new_key,
        )


def normalize_config_layer(layer: dict, source: str) -> dict:
    """
    Rename old config table names, keys and listed values in one TOML layer.

    Only active aliases (scopes marked ``done``) are applied. The input dict is
    never modified; a new dict is returned when changes are made.
    """
    if not isinstance(layer, dict):
        raise TypeError("normalize_config_layer expects a dict")

    table = _table()
    table_entries = active(table.CONFIG_TABLES)
    key_entries = active(table.CONFIG_KEYS)
    value_entries = active(table.CONFIG_VALUES)

    if not table_entries and not key_entries and not value_entries:
        return layer

    changes: list[str] = []
    release = table.ALIAS_LAST_RELEASE

    dotted = [entry for entry in table_entries if "." in entry["old"]]
    single = [entry for entry in table_entries if "." not in entry["old"]]
    dotted.sort(key=lambda entry: len(entry["old"].split(".")), reverse=True)

    # Conflict checks against the original layer.
    for entry in table_entries:
        old_segments = _split_path(entry["old"])
        new_segments = _split_path(entry["new"])
        if _path_exists(layer, old_segments) and _path_exists(layer, new_segments):
            raise LegacyNameConflict(
                f"config: {source} sets both [{entry['old']}] and [{entry['new']}]"
            )

    modules_table = layer.get("modules")
    if isinstance(modules_table, dict):
        for entry in single:
            old_key = entry["old"]
            new_key = entry["new"]
            if old_key in modules_table and new_key in modules_table:
                raise LegacyNameConflict(
                    f"config: {source} sets both [modules].{old_key} and [modules].{new_key}"
                )

    for table_path, table_value in _walk_tables(layer):
        for entry in key_entries:
            old_key = entry["old"]
            new_key = entry["new"]
            if old_key in table_value and new_key in table_value:
                path_text = _format_table_path(table_path)
                old_label = f"[{path_text}].{old_key}" if path_text else f"[].{old_key}"
                new_label = f"[{path_text}].{new_key}" if path_text else f"[].{new_key}"
                raise LegacyNameConflict(f"config: {source} sets both {old_label} and {new_label}")

    result = copy.deepcopy(layer)

    # Dotted table moves.
    for entry in dotted:
        old_segments = _split_path(entry["old"])
        new_segments = _split_path(entry["new"])
        if not _path_exists(result, old_segments):
            continue
        if _path_exists(result, new_segments):
            raise LegacyNameConflict(
                f"config: {source} sets both [{entry['old']}] and [{entry['new']}]"
            )
        value = _path_get(result, old_segments)
        _path_set(result, new_segments, value)
        _path_delete_and_clean(result, old_segments)
        changes.append(f"[{entry['old']}] -> [{entry['new']}]")

    # Single-segment table moves.
    for entry in single:
        old_key = entry["old"]
        new_key = entry["new"]
        if old_key not in result:
            continue
        if new_key in result:
            raise LegacyNameConflict(f"config: {source} sets both [{old_key}] and [{new_key}]")
        result[new_key] = result.pop(old_key)
        changes.append(f"[{old_key}] -> [{new_key}]")

    # Module flags inside [modules].
    if isinstance(result, dict) and isinstance(result.get("modules"), dict):
        modules_dict = result["modules"]
        for entry in single:
            old_key = entry["old"]
            new_key = entry["new"]
            if old_key not in modules_dict:
                continue
            if new_key in modules_dict:
                raise LegacyNameConflict(
                    f"config: {source} sets both [modules].{old_key} and [modules].{new_key}"
                )
            modules_dict[new_key] = modules_dict.pop(old_key)
            changes.append(f"[modules].{old_key} -> [modules].{new_key}")

    # Key aliases at any depth.
    for table_path, table_value in list(_walk_tables(result)):
        for entry in key_entries:
            old_key = entry["old"]
            new_key = entry["new"]
            if old_key not in table_value:
                continue
            if new_key in table_value:
                path_text = _format_table_path(table_path)
                old_label = f"[{path_text}].{old_key}" if path_text else f"[].{old_key}"
                new_label = f"[{path_text}].{new_key}" if path_text else f"[].{new_key}"
                raise LegacyNameConflict(f"config: {source} sets both {old_label} and {new_label}")
            table_value[new_key] = table_value.pop(old_key)
            path_text = _format_table_path(table_path)
            old_label = f"[{path_text}].{old_key}" if path_text else f"[].{old_key}"
            new_label = f"[{path_text}].{new_key}" if path_text else f"[].{new_key}"
            changes.append(f"{old_label} -> {new_label}")

    # Listed value replacements.
    for entry in value_entries:
        old_spec, old_value = entry["old"].rsplit("=", 1)
        new_spec, new_value = entry["new"].rsplit("=", 1)
        old_table_key = old_spec.rsplit(".", 1)
        new_table_key = new_spec.rsplit(".", 1)
        if len(old_table_key) != 2 or len(new_table_key) != 2:
            continue
        new_table_path, new_key = new_table_key
        new_segments = _split_path(new_table_path)
        full_new_segments = new_segments + [new_key]
        if not _path_exists(result, full_new_segments):
            continue
        if _path_get(result, full_new_segments) != old_value:
            continue
        _path_set(result, full_new_segments, new_value)
        changes.append(
            f"[{new_table_path}].{new_key} = {json.dumps(old_value)} -> {json.dumps(new_value)}"
        )

    if changes:
        log.warning(
            "config: %s uses deprecated names %s; they are read until %s",
            source,
            ", ".join(changes),
            release,
        )
    return result if changes else layer


def getenv(name: str, default: str | None = None, *, environ=None) -> str | None:
    """
    Read an environment variable, recognising deprecated names.

    Prefers the new name. Raises ``LegacyNameConflict`` when both old and new
    names are set to different values. Never includes the variable values in
    exceptions or logs.
    """
    if environ is None:
        environ = os.environ

    table = _table()
    entries = active(table.ENV_VARS) + active(table.COMPOSE_VARS)
    name_to_entry: dict[str, dict] = {}
    for entry in entries:
        name_to_entry[entry["old"]] = entry
        name_to_entry[entry["new"]] = entry

    entry = name_to_entry.get(name)
    if entry is None:
        return environ.get(name, default)

    old_name = entry["old"]
    new_name = entry["new"]
    old_value = environ.get(old_name)
    new_value = environ.get(new_name)

    if old_value is not None and new_value is not None and old_value != new_value:
        raise LegacyNameConflict(
            f"environment: {old_name} and {new_name} are both set and differ; unset {old_name}"
        )

    if new_value is not None:
        return new_value

    if old_value is not None:
        if old_name not in _env_warnings_seen:
            _env_warnings_seen.add(old_name)
            log.warning(
                "environment: %s is deprecated, use %s; it is read until %s",
                old_name,
                new_name,
                table.ALIAS_LAST_RELEASE,
            )
        return old_value

    return default


def _alias_action_class(wrapped: argparse.Action) -> type[argparse.Action]:
    """Build an argparse action subclass that logs and delegates to ``wrapped``."""
    new_option = wrapped.option_strings[0]
    release = _table().ALIAS_LAST_RELEASE

    class _AliasAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            option_string = option_string or self.option_strings[0]
            log.warning(
                "cli: %s is deprecated, use %s; it is read until %s",
                option_string,
                new_option,
                release,
            )
            wrapped(parser, namespace, values, option_string=option_string)

    return _AliasAction


def add_cli_aliases(parser: argparse.ArgumentParser) -> None:
    """
    Add hidden deprecated option strings for every active CLI flag alias.

    Aliases are only added when the new option string already exists on the
    parser. The alias delegates to the original action so type, nargs, const
    and choices are preserved.
    """
    for entry in active(_table().CLI_FLAGS):
        new_option = entry["new"]
        target: argparse.Action | None = None
        for action in parser._actions:
            if new_option in action.option_strings:
                target = action
                break
        if target is None:
            continue
        parser.add_argument(
            entry["old"],
            action=_alias_action_class(target),
            help=argparse.SUPPRESS,
            dest=target.dest,
            type=target.type,
            nargs=target.nargs,
            const=target.const,
            choices=target.choices,
            default=target.default,
            metavar=target.metavar,
        )


def resolve_seam(seam: str) -> str:
    """Resolve a deprecated plugin seam name."""
    if not scope_done("keys"):
        return seam
    for entry in active(_table().PLUGIN_SEAMS):
        if seam == entry["old"]:
            log.warning(
                "plugin seam %s is deprecated, use %s; it is read until %s",
                entry["old"],
                entry["new"],
                _table().ALIAS_LAST_RELEASE,
            )
            return entry["new"]
    return seam


def map_module_key(key: str) -> str:
    """Map a single old module key to its new functional key."""
    if not scope_done("keys"):
        return key
    entry = _table().MODULES.get(key)
    if entry is None:
        return key
    return entry["new_key"]


def map_module_keys(mapping: dict) -> dict:
    """Rename dict keys using ``map_module_key``."""
    if not scope_done("keys") or not mapping:
        return mapping

    result: dict = {}
    for key, value in mapping.items():
        new_key = map_module_key(key)
        if new_key == key:
            result[key] = value

    conflicts: list[tuple[str, str]] = []
    for key, value in mapping.items():
        new_key = map_module_key(key)
        if new_key == key:
            continue
        if new_key in result:
            conflicts.append((key, new_key))
            continue
        result[new_key] = value

    if conflicts:
        details = "; ".join(f"{old_key} -> {new_key}" for old_key, new_key in conflicts)
        log.warning(
            "module keys: both old and new names present; keeping new: %s",
            details,
        )
    return result


def map_module_list(names) -> list:
    """Map every item in ``names`` through ``map_module_key``."""
    if not scope_done("keys"):
        return list(names)
    return [map_module_key(name) for name in names]


def map_stream(name: str) -> str:
    """Map a stream name, including its first module segment."""
    if not scope_done("keys"):
        return name
    for entry in active(_table().STREAM_NAMES):
        if name == entry["old"]:
            return entry["new"]
    if "." in name:
        first, rest = name.split(".", 1)
        new_first = map_module_key(first)
        if new_first != first:
            return f"{new_first}.{rest}"
    return name


def map_record(record: dict) -> dict:
    """
    Rename fields and map stream/module values in a top-level record.

    Returns the input unchanged when the ``keys`` scope is pending.
    """
    if not scope_done("keys"):
        return record

    field_map = {entry["old"]: entry["new"] for entry in active(_table().RECORD_FIELDS)}
    result: dict = {}
    for key, value in record.items():
        if key in field_map:
            continue
        result[key] = value

    for key, value in record.items():
        if key not in field_map:
            continue
        new_key = field_map[key]
        if new_key in result:
            _warn_record_both(key, new_key)
            continue
        result[new_key] = value

    for field in ("event_type", "type", "stream"):
        if field in result and isinstance(result[field], str):
            result[field] = map_stream(result[field])

    for field in ("source", "processor", "trigger_module"):
        if field in result and isinstance(result[field], str):
            result[field] = map_module_key(result[field])

    return result


def map_sidecar_dir(name: str) -> str:
    """Map a sidecar directory name."""
    for entry in active(_table().SIDECAR_DIRS):
        if name == entry["old"]:
            return entry["new"]
    return name


def map_bundle_member(name: str) -> str:
    """Map a bundle member path, including module-key prefixes."""
    if not scope_done("keys"):
        return name
    for entry in active(_table().BUNDLE_MEMBERS):
        old_prefix = entry["old"]
        if name.startswith(old_prefix):
            return entry["new"] + name[len(old_prefix) :]
    parts = name.split("/")
    if parts:
        new_first = map_module_key(parts[0])
        if new_first != parts[0]:
            parts[0] = new_first
            return "/".join(parts)
    return name


def map_stage_record(data: dict) -> dict:
    """
    Rename stage field names and stage values.

    Returns the input unchanged when the ``persisted`` scope is pending.
    """
    if not scope_done("persisted"):
        return data

    field_map = {entry["old"]: entry["new"] for entry in active(_table().STAGE_FIELDS)}
    value_map = {entry["old"]: entry["new"] for entry in active(_table().STAGE_VALUES)}
    result: dict = {}
    for key, value in data.items():
        if key in field_map:
            continue
        if key == "stage" and isinstance(value, str):
            value = value_map.get(value, value)
        result[key] = value

    for key, value in data.items():
        if key not in field_map:
            continue
        new_key = field_map[key]
        if new_key in result:
            _warn_record_both(key, new_key)
            continue
        result[new_key] = value
    return result


def lived_artifact_paths() -> tuple[str, ...]:
    """
    Return every lived artifact path, old names first then new names.

    This reader is always active because it only adds recognition.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in _table().LIVED_ARTIFACTS:
        for name in (entry["old"], entry["new"]):
            if name not in seen:
                seen.add(name)
                ordered.append(name)
    return tuple(ordered)
