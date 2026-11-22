# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Compares predictive golden traces; exact for the same-machine check, a float tolerance for the CI fixture check."""

import argparse
import json
import math
from pathlib import Path

CI_REL_TOL = 1e-6


def first_diff(actual, expected, path="", *, rel_tol=0.0):
    if type(actual) is not type(expected):
        return path or "<root>", actual, expected

    if type(actual) is float:
        if math.isnan(actual) and math.isnan(expected):
            return None
        if rel_tol > 0:
            if math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=1e-12):
                return None
        elif actual == expected:
            return None
        return path or "<root>", actual, expected

    if isinstance(actual, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual:
                return f"{path}.{key}" if path else key, "<missing>", expected[key]
            if key not in expected:
                return f"{path}.{key}" if path else key, actual[key], "<missing>"
            if rel_tol > 0 and key.endswith("_digest"):
                continue
            result = first_diff(
                actual[key],
                expected[key],
                f"{path}.{key}" if path else key,
                rel_tol=rel_tol,
            )
            if result is not None:
                return result
        return None

    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}.len", len(actual), len(expected)
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            result = first_diff(
                actual_item,
                expected_item,
                f"{path}[{index}]",
                rel_tol=rel_tol,
            )
            if result is not None:
                return result
        return None

    if actual != expected:
        return path or "<root>", actual, expected
    return None


def compare_dirs(base_dir, head_dir) -> list[str]:
    messages = []
    base = Path(base_dir)
    head = Path(head_dir)

    for path in sorted(base.glob("*.json")):
        name = path.name
        head_path = head / name
        if not head_path.is_file():
            messages.append(f"{name}: missing in head_dir")
            continue

        with path.open() as base_file:
            base_data = json.load(base_file)
        with head_path.open() as head_file:
            head_data = json.load(head_file)

        difference = first_diff(
            base_data["steps"],
            head_data["steps"],
            "steps",
            rel_tol=0,
        )
        if difference is not None:
            difference_path, base_value, head_value = difference
            messages.append(
                f"{name}: first differing {difference_path}: "
                f"base={base_value!r} head={head_value!r}"
            )

    return messages


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare predictive golden trace directories")
    parser.add_argument("base_dir")
    parser.add_argument("head_dir")
    args = parser.parse_args(argv)

    messages = compare_dirs(args.base_dir, args.head_dir)
    for message in messages:
        print(message)
    if not messages:
        print("golden traces identical")
    return 1 if messages else 0


if __name__ == "__main__":
    raise SystemExit(main())
