## ADDED Requirements

### Requirement: Bottom-up fovea saliency is precision-weighted per tile
Topos SHALL keep, for each tile of the spatial saliency grid, an exponential running mean and variance of that tile's change, and SHALL compute the bottom-up saliency of a tile as its change in excess of its running mean divided by the running standard deviation regularised by a floor term proportional to the mean change across tiles, using the statistics from before the current observation. A tile with fewer than five observations SHALL use its raw change. When the combined map is flat, the fovea SHALL hold its previous location, or take the centre when there is none.

#### Scenario: A calm scene holds the fovea
- **WHEN** no tile changes more than usual and the fovea was previously at the upper left
- **THEN** the fovea stays at the upper left

#### Scenario: Habitual flicker loses to unusual change
- **WHEN** one tile changes strongly on every frame and another tile, still for many frames, changes by a smaller amount
- **THEN** the fovea moves to the tile with the unusual change

### Requirement: Foveated views are encoded as real clips
With foveation enabled and a clip encoder, Topos SHALL derive the peripheral and foveal views from every frame in its clip buffer, at the fovea selected on the latest frame, and SHALL encode those multi-frame clips.

#### Scenario: The encoder sees motion
- **WHEN** the clip buffer holds sixteen different frames
- **THEN** the peripheral clip passed to the encoder holds sixteen views derived from those frames, not one view repeated
