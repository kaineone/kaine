# Provision PyAV / perception extras for research installs

## Why

The unified reproducible perception feed (`reproducible-perception`) decodes
playlist media for **both** senses: OpenCV decodes the video track, and
`PlaylistAudioStream` decodes the audio track via **PyAV** (`import av`). PyAV is
not declared in any optional-dependency extra, so on a fresh machine a
`playlist`-mode research run fails the moment Audition starts — the audio source
raises `PerceptionUnavailableError` because `av` is missing.

Two gaps compound this on a research install:

- **PyAV is undeclared.** No extra installs `av`, so even an operator who runs
  `pip install -e .[audio]` does not get the playlist-audio decode dependency.
- **The wizard's extras inference is blind to the feed.** `implied_extras`
  derives `audio`/`vision` only from each module's `capture_enabled` flag, which
  the shipped config leaves **off**. A research run drives perception through
  `[perception_feed].mode`, not those flags, so the wizard installs neither cv2
  nor av for a `playlist` feed.

The default install must stay lean (no heavy cv2/av/funasr for a baseline boot),
so the fix provisions these deps only when a research perception feed actually
needs them.

## What changes

1. **Declare PyAV.** Add `av>=12,<15` to the `[audio]` extra (the home of the
   other Audition deps). Add an aggregate convenience extra
   `perception = ["kaine[audio]", "kaine[vision]"]` — the one name that
   provisions both stimulus surfaces (cv2 video + sounddevice/av audio).

2. **Make the wizard feed-aware.** `implied_extras` ALSO reads
   `[perception_feed].mode`: `playlist` → `vision` + `audio` (decode media);
   `live` → `vision` + `audio` (open camera + mic); `seeded` → nothing (pure
   numpy synthesis, no decode dependency). The returned list is de-duplicated.
   Existing module-based implications are unchanged.

3. **Add a `--research` install flag.** `scripts/install.sh` and its Python port
   `scripts/install.py` gain a `--research` flag that, after the lean `.[test]`
   base install, additionally runs a REAL `pip install -e .[perception]` and
   reports what it did. The default install is unchanged.

4. **Docs.** The reproduction, getting-started, tech-choices, and audition docs
   state that a playlist research run needs the perception extras (via
   `install.sh --research` or `pip install -e .[perception]`), and that seeded
   mode needs neither.

## Impact

- **Affected capability:** `first-run-wizard` (extras inference + dependency
  provisioning).
- **Code:** `pyproject.toml` (`[audio]` gains `av`; new `perception` aggregate),
  `kaine/setup/wizard.py` (`implied_extras` feed-mode logic),
  `scripts/install.sh` + `scripts/install.py` (`--research` flag).
- **Docs:** `docs/reproducing-results.md`, `docs/getting-started.md`,
  `docs/tech-choices.md`, `docs/modules/audition.md`.
- **Default install unchanged:** lean base (`.[test]`) stays the default; the
  heavy decode/capture deps are opt-in via `--research` / `.[perception]` or
  implied only when the feed mode requires them.
- **Honest until installed:** until `.[perception]` (or `.[audio]`) is installed,
  a `playlist` audio source still fails closed with an install hint — no
  synthetic silence.
