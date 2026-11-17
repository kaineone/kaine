# Proposal: maternal voice with short public-domain stories

## Summary
Extend the maternal voice repertoire with takes derived from short public-domain
children's stories, rendered through the approved TTS backend into the same 8 kHz
mono FLAC + 16 kHz stream format the loader requires.

## Motivation
Fetuses show familiarity and preference for material repeatedly exposed to
in utero (DeCasper & Spence 1986; Partanen et al. 2013). Stable stories are a
natural supplement to the live maternal repertoire.

## Scope
- Licence-checked public-domain source texts (PD-1929 or Project Gutenberg).
- TTS via the policy-approved backend, low-passed per config.
- Manifest entries with takes, initial_unlocked, and sha256.
- Tests, review, merge.

## Welfare note
Voice remains supplemental; live maternal voice is the substrate. Stories must
respect 30 s slot boundaries (truncation handled).
