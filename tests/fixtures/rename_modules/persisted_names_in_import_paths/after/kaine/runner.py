# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import kaine.cycle.development as owner_module
from kaine.cycle.development import Owner


class State:
    gestation: bool = False


def run(state):
    return Owner(), owner_module, state.gestation
