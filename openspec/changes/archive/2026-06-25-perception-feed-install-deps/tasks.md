# Tasks — provision PyAV / perception extras for research installs

## 1. Declare the dependencies
- [x] 1.1 Add `av>=12,<15` to the `[audio]` extra in `pyproject.toml` with a
      clear comment (PyAV — playlist-audio track decode for `PlaylistAudioStream`).
- [x] 1.2 Add the aggregate `perception = ["kaine[audio]", "kaine[vision]"]`
      convenience extra with a comment explaining it pulls both stimulus surfaces.
- [x] 1.3 Verify the file parses: `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`.

## 2. Make the wizard feed-aware
- [x] 2.1 In `kaine/setup/wizard.py`, extend `implied_extras` to read
      `[perception_feed].mode`: `playlist`/`live` → add `vision` + `audio`;
      `seeded` → add nothing. De-duplicate the returned list. Update the docstring.
- [x] 2.2 Keep the existing module-based implications unchanged.

## 3. Add the `--research` install flag
- [x] 3.1 `scripts/install.sh`: add `--research` that, after `.[test]`, runs a REAL
      `pip install -e .[perception]` and prints what it did; update the usage/help
      text (and the `--help` sed range).
- [x] 3.2 `scripts/install.py`: mirror the flag identically (documented port).

## 4. Docs
- [x] 4.1 `docs/reproducing-results.md`: note `install.sh --research` /
      `.[perception]` for the playlist-audio path.
- [x] 4.2 `docs/getting-started.md`: document the `perception` aggregate + that
      `[audio]` now includes PyAV; seeded needs neither.
- [x] 4.3 `docs/tech-choices.md`: add the `av` row + the aggregate-extra note.
- [x] 4.4 `docs/modules/audition.md`: point the playlist install hint at
      `.[perception]`.

## 5. Tests
- [x] 5.1 Extend `tests/test_setup_wizard.py`: `implied_extras` adds `vision`+`audio`
      for `mode="playlist"` and `mode="live"`, and nothing extra for `mode="seeded"`;
      assert de-duplication.

## 6. Verify
- [x] 6.1 `openspec validate perception-feed-install-deps --strict` passes.
- [x] 6.2 Full suite green (`.venv/bin/pytest -q`); `lint-imports` green.
- [x] 6.3 Do NOT install `av` (heavy) — the suite stays green without it.
