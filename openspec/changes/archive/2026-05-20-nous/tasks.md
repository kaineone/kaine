## 1. Setup script and external

- [ ] 1.1 Add `external/` to `.gitignore`
- [ ] 1.2 Write `scripts/build-ona.sh` — idempotent clone + build of opennars/OpenNARS-for-Applications
- [ ] 1.3 Run the script on this host; confirm `external/OpenNARS-for-Applications/NAR --version` (or equivalent smoke test) exits 0

## 2. Narsese helpers

- [ ] 2.1 Implement `kaine/modules/nous/narsese.py` — `TruthValue` dataclass, `slugify_atom(s)`, `make_belief(source, type_, salience, *, confidence=0.9)`, `parse_derivation_line(line)`
- [ ] 2.2 Tests in `tests/test_nous_narsese.py` covering the helpers (slug edge cases, truth-value parse, derivation parse round-trip)

## 3. Subprocess wrapper

- [ ] 3.1 Implement `kaine/modules/nous/process.py` with `NARProcessProtocol` and `NARProcess` (asyncio subprocess)
- [ ] 3.2 `FakeNARProcess` test double with scriptable derivation queue and lifecycle assertions
- [ ] 3.3 Tests in `tests/test_nous_process.py` exercising `FakeNARProcess` thoroughly; one opt-in test (`KAINE_NOUS_RUN_REAL_NAR=1`) launches the real binary

## 4. Translator

- [ ] 4.1 Implement `kaine/modules/nous/translator.py` with `EventTranslator.translate(event) -> list[str]` returning Narsese statements
- [ ] 4.2 Tests in `tests/test_nous_translator.py` covering the v1 template, salience clamping, causal-parent implication

## 5. Module

- [ ] 5.1 Implement `kaine/modules/nous/module.py` with `Nous(BaseModule)` — initialize starts the subprocess and the derivation polling task; on_workspace translates+feeds; shutdown stops cleanly; restart backoff
- [ ] 5.2 Update `kaine/modules/__init__.py` to export `Nous`
- [ ] 5.3 Add `kaine.modules.nous` to setuptools packages

## 6. Config

- [ ] 6.1 Add `[nous]` block to `config/kaine.toml`
- [ ] 6.2 Add `nous = false` under `[modules]`

## 7. Tests

- [ ] 7.1 `tests/test_nous_module.py` — fake subprocess: workspace broadcast → Narsese sent → derivation read → nous.belief published; restart-on-crash backoff exercised; ser/de
- [ ] 7.2 Full unit suite passes

## 8. Verification

- [ ] 8.1 `openspec validate nous --strict` clean
- [ ] 8.2 Update `DEPENDENCIES.md` adding the ONA row (license: MIT, location: `external/OpenNARS-for-Applications/`)
- [ ] 8.3 Commit, merge, archive change, drop branch
