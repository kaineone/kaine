# SPDX-FileCopyrightText: 2024 KAINE Project
# SPDX-License-Identifier: MIT

"""Top-level package for KAINE."""

# Existing imports (if any) are preserved.
# Added promotion utilities to the public API.

from .promotion import promote, TrainerResultRefusedError

# Preserve existing __all__ if defined; otherwise initialise.
try:
    __all__
except NameError:
    __all__ = []

# Ensure the promotion symbols are exported.
if "promote" not in __all__:
    __all__.append("promote")
if "TrainerResultRefusedError" not in __all__:
    __all__.append("TrainerResultRefusedError")