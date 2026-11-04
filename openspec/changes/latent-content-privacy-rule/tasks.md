## 1. Code changes

- [ ] 1.1 Add `LATENT_CONTENT_FIELDS: frozenset[str] = frozenset()` to `kaine/privacy_filter.py` beside `CONTENT_FIELDS`.
- [ ] 1.2 Update `PrivacyFilter.fields()` to return `CONTENT_FIELDS | LATENT_CONTENT_FIELDS | self.extra_content_fields`.
- [ ] 1.3 Add docstring to `LATENT_CONTENT_FIELDS` explaining the rule: fields here are latent-derived cognitive content, stripped from every external surface, never in the research log, never in episodic traces.

## 2. CI and test guards

- [ ] 2.1 New `tests/test_latent_content_privacy.py` with:
  - A test asserting no key in `LATENT_CONTENT_FIELDS` appears in any `_TAXONOMY` entry's kept-keys list in `research_event_observer.py`.
  - A test asserting no event type whose payload keys overlap `LATENT_CONTENT_FIELDS` is in `INTERNAL_EVENT_TYPES`.
  - A test asserting `PrivacyFilter().fields()` is a superset of `LATENT_CONTENT_FIELDS`.
- [ ] 2.2 Extend `tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_module_publishers` to also cover `LATENT_CONTENT_FIELDS`.

## 3. Documentation

- [ ] 3.1 `docs/13-security-and-privacy.md`: section on latent-derived content privacy rule.
- [ ] 3.2 `docs/02-architecture/boundaries.md`: row for latent-content boundary.

## 4. Review and merge

- [ ] 4.1 Worker first-pass review (beam:cloud).
- [ ] 4.2 Second review (SR): Claude adversarial review — verify the privacy boundary is complete, no content path bypasses the filter, guards catch the right failures.
- [ ] 4.3 Merge to main.
