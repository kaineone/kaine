# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Command line for the model server: ``python -m kaine.setup.model_server start|status|stop``.

The implementation lives in :mod:`kaine.organ_server.lifecycle`, which the
runtime also uses; this entry point keeps the bootstrap scripts and docs working.
"""
from kaine.organ_server.lifecycle import main

if __name__ == "__main__":
    raise SystemExit(main())
