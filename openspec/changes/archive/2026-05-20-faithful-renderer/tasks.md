## 1. Package

- [ ] 1.1 Add `kaine.faithful` to setuptools packages
- [ ] 1.2 Create `kaine/faithful/__init__.py`

## 2. Templates

- [ ] 2.1 Implement `kaine/faithful/templates.py` — TEMPLATES registry mapping `(source, type)` to a callable; fallback template for unknown keys
- [ ] 2.2 Templates for soma.report, chronos.report, topos.report, nous.belief, mnemos.recall, thymos.emotion, thymos.drive, thymos.state, thymos.goal, eidolon.drift, cycle.tick

## 3. Renderer

- [ ] 3.1 Implement `kaine/faithful/renderer.py` with `FaithfulRenderer.render_event(event)` and `render_snapshot(snapshot)`

## 4. Tests

- [ ] 4.1 `tests/test_faithful_templates.py` — every shipped template renders to a non-empty plain-text string with no banned phrases
- [ ] 4.2 `tests/test_faithful_renderer.py` — determinism, fallback for unknown source, snapshot composition, empty snapshot

## 5. Verification

- [ ] 5.1 Full unit suite passes
- [ ] 5.2 `openspec validate faithful-renderer --strict` clean
- [ ] 5.3 Commit, merge, archive change, drop branch
