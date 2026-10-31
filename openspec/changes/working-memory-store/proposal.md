## Why

KAINE has no working memory. The processors read the latest accessed broadcast as their context, and the next accessed broadcast replaces it, so nothing that was accessed is held across broadcasts (paper §3.2, A.1). The language organ's notes are built from the latest coalition only (`kaine/modules/language/context.py`, `assemble`). The revised paper says so in §9: "There is no working memory beyond the latest access summary". The architecture-completeness notes of 2026-10-31 place this among the missing components of the Common Model of Cognition (Laird, Lebiere, and Rosenbloom 2017), whose working memory is the buffer the cognitive cycle tests and changes (E5; work plan W2(c)).

The docs call something else working memory. "The short-term buffer is working memory" (`docs/09-modules/episodic-memory.md`, Collections; `docs/06-operation/development.md`) describes the episodic memory module's 128-entry FIFO of every broadcast, accessed or inhibited, which only that module reads. It is the fast store's staging area, not a buffer of accessed contents.

The approved capacity design of 2026-10-31 sets access to one content per broadcast (K = 1), after the one-item focus of attention (Oberauer 2002) and single-assembly ignition (Dehaene, Sergent, and Changeux 2003), and names a store of about four recently accessed contents as the follow-on that carries the multi-item context (Cowan 2001; Oberauer 2002). Access is the focus; the store is the region of direct access around it. This change designs that store.

Design only. Nothing is built until the first module-addition study has finished, because the store changes the processors' context and the organ's notes, which the workspace-mediation test and the study measure.

## What Changes

- A working-memory store in the workspace: up to `capacity` entries (default 4), each an accessed member with the tick, the entity time and the score at which it was accessed. It is filled only from accessed members. A newly accessed member replaces the entry of the same source and event type and moves to the front; otherwise the oldest entry is displaced when the store is full. An entry older than `max_age_s` is dropped. The store is cleared at sleep onset and at boot, and is never persisted.
- The store never competes for access and publishes no event. Each broadcast carries the store's entries in a new snapshot field, `held`, in the order newest first.
- Two uses, each behind its own switch, selected by `[working_memory].arm`:
  - `notes`: the organ's awareness block renders the held entries after the current coalition, each felt line preceded by a graded recency phrase ("just now", "a moment ago", "a little while ago"), within the existing event and character caps.
  - `context`: the processors' context is built from the held entries in place of the latest accessed broadcast's members, with each entry's own age; A.8's null context is built by the same rule over the same entries.
  - `off` (shipped) and `both` complete the arms. With `off` nothing is built and every broadcast, context and prompt is bit for bit the current build.
- With `capacity = 1` and one access per broadcast, the `context` arm equals the current context, which gives the change a built-in equivalence check.
- The docs stop calling the episodic memory module's short-term buffer working memory.

## Capabilities

### New Capabilities

- `working-memory`: the store of recently accessed contents, its filling and displacement rules, and its two uses.

### Modified Capabilities

- `language`: with the `notes` or `both` arm, the awareness block renders the held entries after the current coalition.

## Impact

- Code: new `kaine/workspace/working_memory.py`; `kaine/workspace/core.py` (the `held` field after the access decision); `kaine/cycle/types.py` (`WorkspaceSnapshot.held`); `kaine/modules/context.py` (`BroadcastContext` adopts the held entries under the `context` arm); `kaine/modules/language/context.py` (notes); `kaine/faithful/felt.py` (recency phrases); `kaine/cycle/ignition_log.py` (held entry ids and ages only); `config/kaine.toml`; study files for the arms.
- Docs: global workspace chapter, language chapter, episodic memory chapter (the short-term buffer relabelled), operation chapter, configuration appendix.
- Behaviour: none with the shipped configuration.
- Calibration: a planned test that uses the `context` arm needs its own positive control, principal components and minimum effect, measured on the store's context.
- Welfare: both arms change what the entity is aware of (`notes`) or how its processors predict (`context`). Every PR gets the independent second review.
- Paper: §3.2 (the context), §3.5 (the organ's notes), A.1 and A.8 (context and null over the store), Table A1 (`capacity`, `max_age_s`, the recency bins), §9 (the working-memory bullet).
