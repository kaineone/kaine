# SPDX-FileCopyrightText: 2023 KAINE
# SPDX-License-Identifier: MIT

from typing import List

class Sound:
    def __init__(self, name: str, path: str, planned_set: List[str]) -> None:
        """Initialize a Sound instance.

        Args:
            name: The unique identifier for the sound.
            path: Filesystem path to the sound file.
            planned_set: List of planned‑set identifiers associated with this sound.

        Raises:
            ValueError: If ``planned_set`` is empty.
            TypeError: If ``planned_set`` is not a list of strings.
        """
        if not isinstance(planned_set, list):
            raise TypeError("planned_set must be a list of strings")
        if not all(isinstance(item, str) for item in planned_set):
            raise TypeError("planned_set must be a list of strings")
        if not planned_set:
            raise ValueError("planned_set must be provided for a new sound")
        self.name = name
        self.path = path
        self.planned_set = planned_set

    # Existing behaviours (methods, properties, etc.) remain unchanged.