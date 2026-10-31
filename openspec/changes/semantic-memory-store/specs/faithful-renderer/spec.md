## ADDED Requirements

### Requirement: Semantic recall renders as knowledge
A felt recall line whose `content.kind` is `"semantic"` SHALL begin "I know this kind of moment:" and render each gist kind in the habitual present with a frequency word from its share: "often" from one half, "usually" from 0.7, "almost always" from 0.9. It SHALL add the affect mean in the same form and, with `own_words_share` of at least one half, "and I often have something to say". It SHALL contain no digit and SHALL NOT begin "I remember".

#### Scenario: A gist renders with frequency words
- **WHEN** a semantic recall's gist holds a vision report graded sudden at share 0.8 and a calm affect mean
- **THEN** the line reads "I know this kind of moment: usually what I see is sudden, and I usually feel calm."

#### Scenario: Knowledge is not rendered as a memory
- **WHEN** any semantic recall is rendered
- **THEN** the line begins "I know this kind of moment:" and contains no "I remember"
