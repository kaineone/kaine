from pathlib import Path

import tomllib

from kaine.config import list_all_defaults


CANDIDATES = (
    Path("config/reference.toml"),
    Path("docs/config_defaults.toml"),
    Path("docs/reference.toml"),
    Path("config/kaine.reference.toml"),
)


def test_reference_matches_list_all_defaults():
    existing = [path for path in CANDIDATES if path.exists()]
    if not existing:
        # No committed reference file yet; nothing to drift-check.
        return

    expected = list_all_defaults()
    for path in existing:
        with path.open("rb") as fh:
            actual = tomllib.load(fh)
        assert actual == expected, f"reference file drift: {path}"