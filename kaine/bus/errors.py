# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

class BusError(Exception):
    pass


class EventValidationError(BusError):
    pass


class ReservedStreamError(BusError):
    pass


class BusConfigError(BusError):
    pass


class BusSecurityError(BusError):
    pass
