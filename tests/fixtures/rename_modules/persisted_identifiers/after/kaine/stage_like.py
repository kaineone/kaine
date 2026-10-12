# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from dataclasses import dataclass


@dataclass
class State:
    hypnos_cursor: str | None = None


def read(data: dict, sleep_stream: str) -> State:
    return State(hypnos_cursor=data.get("hypnos_cursor"))
