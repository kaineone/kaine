## ADDED Requirements

### Requirement: Hedge phrases are counted as whole phrases
`output_characteristics` SHALL report `hedge_word_count` as the number of distinct
phrases from `HEDGE_WORDS` that occur in the normalised text (Unicode NFKC,
typographic apostrophes mapped to straight ones, case-folded, whitespace collapsed)
with no `[a-z0-9']` character immediately before or after the phrase.

#### Scenario: Words that contain a hedge are not hedges
- **WHEN** the text is "A mighty wave disappears; rain is unlikely."
- **THEN** `hedge_word_count` is 0

#### Scenario: Hedges are counted once each
- **WHEN** the text is "I might go. It appears likely, and I might stay."
- **THEN** `hedge_word_count` is 3
