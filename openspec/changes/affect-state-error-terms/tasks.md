## 1. Implementation

- [x] 1.1 Factor the per-source error terms out of `_progress` and the valence target out of `_tick` into helpers, with the dynamics unchanged
- [x] 1.2 Add the valence-target terms to the periodic and reset `affect.state` payloads, keyed by a fixed source table, null where undefined
- [x] 1.3 Allowlist the terms in the research event observer and declare their ranges in the post-run log range check
- [x] 1.4 Tests: values match `_progress`, the wellness means and the target on constructed inputs; null for an absent source; every value finite or null; fixed key set; the research record keeps every field
- [x] 1.5 Docs: the affect module page and the research event streams page
