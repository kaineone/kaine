# first-run-wizard (delta: perception-feed install dependencies)

## ADDED Requirements

### Requirement: Perception-feed extras are provisioned for research installs

The wizard's extras inference SHALL imply the perception-feed decode/capture
dependencies from the configured `[perception_feed].mode`, independently of each
module's `capture_enabled` flag, so a fresh research install can decode playlist
media. When `mode` is `playlist` (decodes media) or `live` (opens devices),
`implied_extras` SHALL add both the `vision` extra (OpenCV video track) and the
`audio` extra (which provisions PyAV `av` for the playlist audio track, plus the
microphone deps). When `mode` is `seeded` (pure-numpy synthesis) it SHALL add
neither. The returned extras list SHALL be de-duplicated. The aggregate
`perception` extra SHALL pull both `audio` and `vision`, and the installer
(`scripts/install.sh` and `scripts/install.py`) SHALL provide a `--research` flag
that runs a real `pip install -e .[perception]` after the lean base install, with
the default install left unchanged.

#### Scenario: Playlist feed implies both surfaces' extras

- **WHEN** the configured `[perception_feed].mode` is `playlist`
- **THEN** `implied_extras` includes both `vision` and `audio` (the latter carries
  PyAV for the playlist audio-track decode), regardless of the per-module
  `capture_enabled` flags

#### Scenario: Live feed implies both surfaces' extras

- **WHEN** the configured `[perception_feed].mode` is `live`
- **THEN** `implied_extras` includes both `vision` and `audio`

#### Scenario: Seeded feed implies no decode extras

- **WHEN** the configured `[perception_feed].mode` is `seeded`
- **THEN** `implied_extras` adds neither `vision` nor `audio` for the feed (seeded
  synthesis needs no cv2 or av), and any extras it returns are de-duplicated

#### Scenario: The research install provisions the perception extras

- **WHEN** an operator runs `scripts/install.sh --research` (or its `install.py`
  port) on a fresh machine
- **THEN** after the lean base install it runs a real `pip install -e .[perception]`
  (audio + vision, including PyAV) and reports what it installed, while a default
  install without `--research` stays lean
