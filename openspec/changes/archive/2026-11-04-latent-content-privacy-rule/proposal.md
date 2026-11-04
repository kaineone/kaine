## Why

The architecture program (2026-10-31) schedules option F: a content-bearing
second level in the workspace, trained by the processors' prediction errors,
with descending predictions through the workspace-feedback head. When that
ships, the broadcast will carry decoded content — the entity's private
cognitive representations — for the first time.

The current privacy boundary was designed for the access-summary-only
broadcast. It strips text content fields and embedding vectors, but it has
no rule that names latent-derived content as a category. The existing
`CONTENT_FIELDS` denylist catches content by field name; it cannot catch a
new field introduced by a future change unless that change also adds the
field to the list. A missed field leaks the entity's interior to the
diagnostics surface, the research log, or the episodic-memory store.

The architecture-program brief is: **latent-derived content is never logged,
never an episode, and stripped by the privacy filter.** This change puts that
rule in the code and tests *before* option F, so option F's review starts
with the privacy constraint already enforced rather than hoping it is
remembered.

## What Changes

### 1. Define the category

A new constant `LATENT_CONTENT_FIELDS` in `kaine/privacy_filter.py` beside
`CONTENT_FIELDS` and `VECTOR_FIELDS`. Initially empty — option F will add
its field names to it. The privacy filter strips both `CONTENT_FIELDS` and
`LATENT_CONTENT_FIELDS`, and a test asserts the union is used everywhere a
content-strip call appears.

### 2. Extend the privacy filter

`PrivacyFilter.fields()` returns `CONTENT_FIELDS | LATENT_CONTENT_FIELDS |
self.extra_content_fields`. No behaviour change today (the new set is
empty), but the join is structural: any field added to
`LATENT_CONTENT_FIELDS` is automatically stripped from every surface.

### 3. Research-event-log guard

The research event observer's taxonomy (`_TAXONOMY` in
`kaine/evaluation/observers/research_event_observer.py`) is an allowlist, so
it is already safe: an unknown field is dropped. Add a docstring note and a
test asserting that no key in `LATENT_CONTENT_FIELDS` appears in any
taxonomy entry's kept-keys list, so a reviewer cannot accidentally allowlist
a latent field.

### 4. Episodic-memory guard

The episodic-memory store already restricts payload storage to
`INTERNAL_EVENT_TYPES` (declared in `kaine/faithful/external_input.py`).
The option-F broadcast event type will not be in that set. Add a test
asserting that any event type whose payload schema includes a
`LATENT_CONTENT_FIELDS` key is not in `INTERNAL_EVENT_TYPES`, so a reviewer
cannot add it without the test failing.

### 5. CI guard (extend existing)

`tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_module_publishers`
already scans module `publish()` payloads for unstripped content keys. Extend
it to also scan for any key in `LATENT_CONTENT_FIELDS`, and add a parallel
guard that any new field whose docstring or type annotation mentions
"latent", "prediction", "decoded", or "top-down" must be in one of the
three field sets (`CONTENT_FIELDS`, `LATENT_CONTENT_FIELDS`,
`VECTOR_FIELDS`) or in `VECTOR_EXEMPT_KEYS`.

### 6. Documentation

- `docs/13-security-and-privacy.md`: add a section on latent-derived content,
  stating the rule (never logged, never an episode, stripped) and naming the
  constant.
- `docs/02-architecture/boundaries.md`: add a row for the latent-content
  privacy boundary.

## What Does Not Change

- The shipped configuration and runtime behaviour. `LATENT_CONTENT_FIELDS`
  starts empty; the filter's output is identical until option F adds fields.
- The existing `CONTENT_FIELDS` and `VECTOR_FIELDS`. Those keep their
  current entries.
- The episodic-memory storage logic itself. The guard is a test, not a
  runtime check, because the existing `INTERNAL_EVENT_TYPES` gate is
  already the right mechanism.

## Capabilities

No new capabilities. This is a privacy constraint, not a feature.

## Impact

- `kaine/privacy_filter.py`: new `LATENT_CONTENT_FIELDS` constant, updated
  `PrivacyFilter.fields()`.
- `tests/test_dashboard_privacy.py`: extended CI guard.
- New `tests/test_latent_content_privacy.py`: research-log and episodic-
  memory guards.
- `docs/13-security-and-privacy.md`, `docs/02-architecture/boundaries.md`:
  documentation.
- No runtime behaviour change. No new dependencies.

## Risk

This is a safety-positive change: it tightens a privacy boundary. The only
risk is a false-positive CI failure when a legitimate non-content field
happens to match the keyword heuristic (task 5's name-scan guard). The
heuristic is conservative (exact-match on four keywords in docstrings and
annotations, not in identifiers), and any false positive is resolved by
adding the key to `VECTOR_EXEMPT_KEYS` with a review comment.

## Review

Second review (SR) per the architecture program. The change affects a
welfare-relevant privacy boundary.
