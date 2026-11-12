## Why

Episodic traces in `kaine/modules/episodic_memory/memory.py` store content (text, vector, payload) and affect metadata (valence, intensity, emotion label) but carry no record of the perceptual context at encoding time. The recall system returns matches ranked by content similarity. It cannot distinguish "I remember this content" from "I remember this content in that specific context": who was present, what the entity was perceiving, what its interoceptive state was.

Tulving (1985) formalized the remember/know distinction: remembering includes the context of the original experience, knowing does not. The source monitoring framework (Johnson, Hashtroudi, and Lindsay 1993, Psychological Bulletin) explains source memory failures as the loss of encoding context. Hippocampal pattern completion in rodents (Leutgeb et al. 2007) retrieves context along with content. For a synthetic entity, source memory is what separates "this idea seems familiar" from "I had this idea while watching that film with that person speaking."

KAINE's current recall returns only content similarity. The language module, when rendering a memory into speech, has no context to draw on. The entity cannot say where it encountered a remembered fact or who it was with when the memory formed. Every recall is a "know," never a "remember."

## What Changes

A context signature on every episodic trace, computed at encoding time and used at recall:

1. A `context_signature` field added to the trace payload at storage time. The signature is a compact dict capturing the encoding context: active perceptual locus (which perception feed was active, or live input), active social cognition agents (who the entity was interacting with, by agent id, not by name or content), interoceptive state (arousal level, valence), and temporal context (entity time, time since last sleep).

2. The signature is computed from the current workspace state when the trace enters the STM buffer. The workspace already carries all these signals; the context signature samples them into a fixed-schema dict attached to the trace.

3. Recall returns both a content similarity score (existing cosine on the main vector) and a context similarity score (overlap or weighted match on the context dict's fields). The two scores are reported separately in the recall result, so consumers can distinguish high-content/low-context matches (semantic familiarity) from high-content/high-context matches (episodic remembering).

4. The language module, when rendering a recalled memory, can use the context similarity and the context fields to produce richer descriptions. A high-context match carries enough information to say "I remember this from when X was speaking" or "this reminds me of something I noticed during a film"; a low-context match produces only "this seems familiar."

5. The context signature is content-free by the same rule the episodic memory module already follows: no transcripts, no raw perception, no identifying information beyond agent ids that the social cognition module already publishes. The signature records that a specific social agent was present, not what they said.

## Impact

- Code: `kaine/modules/episodic_memory/memory.py` (signature computation, dual scoring at recall), `kaine/modules/episodic_memory/module.py` (workspace state sampling at store time), `kaine/modules/episodic_memory/storage.py` (payload schema extension).
- Licence: no new dependency.
- Risk: LOW. The signature is a payload extension; existing traces without it recall as before (context score is zero or absent). No migration needed for the existing episodic collection since Qdrant payloads are schema-free. The workspace sampling adds one dict construction per store, which is negligible.
