## ADDED Requirements

### Requirement: Bottom-up fovea saliency is precision-weighted per tile
Topos SHALL keep, for each tile of the spatial saliency grid, an exponential running mean and variance of that tile's change, and SHALL compute the bottom-up saliency of a tile as its change in excess of its running mean divided by the running standard deviation, floored, using the statistics from before the current observation. A tile with fewer than five observations SHALL use its raw change.

#### Scenario: Habitual flicker loses to unusual change
- **WHEN** one tile changes strongly on every frame and another tile, still for many frames, changes by a smaller amount
- **THEN** the fovea moves to the tile with the unusual change

### Requirement: Foveated views are encoded as real clips
With foveation enabled and a clip encoder, Topos SHALL derive the peripheral and foveal views from every frame in its clip buffer, at the fovea selected on the latest frame, and SHALL encode those multi-frame clips.

#### Scenario: The encoder sees motion
- **WHEN** the clip buffer holds sixteen different frames
- **THEN** the peripheral clip passed to the encoder holds sixteen views derived from those frames, not one view repeated
