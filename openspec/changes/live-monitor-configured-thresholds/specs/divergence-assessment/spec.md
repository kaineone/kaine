## ADDED Requirements

### Requirement: Live preservation and decommission use the same consolidation thresholds
The live divergence monitor SHALL assess divergence with the consolidation thresholds configured in `[hypnos.voice_alignment]` (`consolidation_divergence_rate_threshold`, `consolidation_divergence_magnitude_threshold`), read the same way the decommission CLI reads them, so the two consumers reach the same verdict on the same records.

#### Scenario: A lowered rate threshold is honoured live
- **WHEN** `consolidation_divergence_rate_threshold = 0.2` and the latest consolidation record has `divergence_rate = 0.3`
- **THEN** the live monitor's assessment reports organ-level divergence, as the decommission CLI's does
