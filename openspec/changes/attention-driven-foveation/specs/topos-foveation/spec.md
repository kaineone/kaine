# topos-foveation

## ADDED Requirements

### Requirement: Coarse spatial saliency map

Topos SHALL compute a coarse spatial saliency map over the current frame by tiling
the frame into a fixed grid and scoring each tile by its change (feature distance to
the previous frame) and its localized forward-model prediction error. The map SHALL
be held in process memory only and SHALL NOT be written to disk.

#### Scenario: A localized surprise raises one region

- **WHEN** a change occurs in one region of an otherwise static frame
- **THEN** that region's tiles score higher than the unchanged tiles in the saliency
  map

#### Scenario: Map is memory-only

- **WHEN** the spatial saliency map is computed
- **THEN** no raw frame, tile image, or pixel buffer is written to disk

### Requirement: Precision-weighted fovea-target selection

Topos SHALL select a fovea target from the saliency map as the precision-weighted
combination of the bottom-up saliency and an optional top-down bias region, and
SHALL derive the fovea size from Thymos arousal. With no top-down bias present the
target SHALL be the bottom-up saliency argmax. Target updates SHALL be damped by a
dwell/hysteresis rule so the fovea does not oscillate between comparable regions.

#### Scenario: Bottom-up only when no top-down bias

- **WHEN** no top-down bias region is provided
- **THEN** the fovea target is the centre of the highest-saliency region

#### Scenario: Top-down bias shifts the target

- **WHEN** a top-down bias region is provided over a moderately-salient region while
  a slightly-more-salient region has no bias
- **THEN** the precision-weighted target can fall on the biased region rather than
  the raw saliency argmax

#### Scenario: Arousal sets fovea size

- **WHEN** Thymos arousal differs between two ticks
- **THEN** the selected fovea size changes monotonically with arousal (this is a
  distinct visual coupling, not the Syneidesis salience-selection window; the default
  mapping follows the arousal-narrowing effect — higher arousal, tighter fovea — and
  the sign is a tuning parameter)

#### Scenario: Comparable regions do not thrash

- **WHEN** two regions have near-equal saliency across consecutive ticks
- **THEN** the fovea target does not flip between them every tick (dwell/hysteresis
  holds it until one clearly dominates)

### Requirement: Peripheral and foveal views from one in-memory grab

When foveation is enabled, Topos SHALL derive both a downsampled peripheral view of
the whole frame and a foveal crop around the fovea target from a single
in-memory screen grab, and SHALL release each grabbed frame as it ages out. No
grabbed frame, peripheral view, or foveal crop SHALL be written to disk.

#### Scenario: Both views come from one grab

- **WHEN** a tick produces a peripheral and a foveal view
- **THEN** both are derived from the same single grabbed frame held in memory

#### Scenario: Zero raw-sense-data persistence preserved

- **WHEN** foveation runs for any number of ticks
- **THEN** no raw frame, peripheral, or foveal pixel data is ever written to disk

### Requirement: Saccadic native region re-capture

If a native-resolution region capture pinned to the fovea is enabled, Topos SHALL
re-pin the capture region only when the fovea target moves beyond a configured
hysteresis threshold and a minimum dwell has elapsed (a saccade), and SHALL NOT
reconfigure the region capture on every tick.

#### Scenario: No reconfiguration during a fixation

- **WHEN** the fovea target stays within the hysteresis threshold across consecutive
  ticks
- **THEN** the native region capture is not re-pinned

#### Scenario: Re-pin on a saccade

- **WHEN** the fovea target moves beyond the hysteresis threshold after the minimum
  dwell
- **THEN** the native region capture re-pins to the new region

### Requirement: Content-free fovea publication

Topos SHALL publish the fovea location and size as content-free normalized values
(coordinates and size in [0, 1]) and SHALL NOT include any pixel data with them.
Where a predicted next fovea is produced, it SHALL likewise be content-free.

#### Scenario: Fovea location carries no pixels

- **WHEN** the fovea location is published
- **THEN** it contains only normalized numeric coordinates and size, and no image or
  pixel buffer

### Requirement: Foveation is off by default with a uniform fallback

Foveation SHALL be disabled by default, and when disabled Topos SHALL produce the
existing single whole-frame latent and salience unchanged.

#### Scenario: Default install is unchanged

- **WHEN** the shipped configuration is used without enabling foveation
- **THEN** Topos emits a single whole-frame latent exactly as before this change
