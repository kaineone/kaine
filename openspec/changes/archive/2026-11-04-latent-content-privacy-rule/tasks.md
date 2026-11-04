## 1. Code changes

- [x] 1.1 Add `LATENT_CONTENT_FIELDS: frozenset[str] = frozenset()` to `kaine/privacy_filter.py` beside `CONTENT_FIELDS`.
- [x] 1.2 Update `PrivacyFilter.fields()` to return `CONTENT_FIELDS | LATENT_CONTENT_FIELDS | self.extra_content_fields`.
- [x] 1.3 Add docstring to `LATENT_CONTENT_FIELDS` explaining the rule: fields here are latent-derived cognitive content, stripped from every external surface, never in the research log, never in episodic traces.

## 2. CI and test guards

- [x] 2.1 New `tests/test_latent_content_privacy.py` with:
  - A test asserting no key in `LATENT_CONTENT_FIELDS` appears in any `_TAXONOMY` entry's kept-keys list in `research_event_observer.py`.
  - A test asserting no event type whose payload keys overlap `LATENT_CONTENT_FIELDS` is in `INTERNAL_EVENT_TYPES`.
  - A test asserting `PrivacyFilter().fields()` is a superset of `LATENT_CONTENT_FIELDS`.
- [x] 2.2 Extend `tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_module_publishers` to also cover `LATENT_CONTENT_FIELDS`.

## 3. Documentation

- [x] 3.1 `docs/13-security-and-privacy.md`: section on latent-derived content privacy rule.
- [x] 3.2 `docs/02-architecture/boundaries.md`: row for latent-content boundary.

## 4. Review and merge

- [x] 4.1 Worker first-pass review (beam:cloud). 4 findings, all verified: 0 confirmed bugs.
- [x] 4.2 Second review (SR): Claude adversarial review — D8 checklist PASS. Two notes for option F: (a) episodic store field-level path relies on type-level guard; (b) dev_content_override passes latent fields (same as regular content, documented).
- [x] 4.3 Merge to main. PR #656, CI required gates pass, enqueued.
