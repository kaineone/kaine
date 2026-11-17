# Design: maternal voice stories

## Inputs
- Public-domain text, licence verified.
- Chunked to <= 30 s slot (slot_seconds).

## Output
- 8 kHz mono FLAC takes under kaine/modules/audition/maternal_voice_data/.
- Manifest: format, items, takes, sample_rate (8000), initial_unlocked, manifest_sha256.
- Loader requirement: stream sample rate 16000 (2x file rate).

## Awake-time gating
- Unlocks follow awake_seconds and unlock_seconds; no per-slot scheduling changes.

## Welfare
- Content-free tagging (item ids + durations only in records).
