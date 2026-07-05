# Structural import-boundary enforcement (replace the grep with contracts)

## Why

The sidecar boundary is load-bearing: `kaine.evaluation` is the observe-only
research subsystem, and core runtime (cycle, workspace, modules, lifecycle, nexus
internals) must run with it entirely absent — so core must never import
`kaine.evaluation`; only the two composition-root entrypoints
(`kaine/cycle/__main__.py`, `kaine/nexus/__main__.py`) may wire it in.

Today this is enforced by a single test that `git grep`s for
`from kaine.evaluation` across `kaine/` and subtracts the allowed entrypoints. That
enforcement is weak in three ways:

- **It's slow to surface.** The test lives in the ~8-minute full suite, so a
  violation is discovered only after a full run — repeatedly, this session, a
  violation passed targeted tests and was caught only by the full suite.
- **It's invisible to the tools developers/agents actually use.** A forbidden
  import compiles, type-checks, and passes `-k` selections; nothing flags it at
  edit/lint time.
- **It's a brittle string match**, not a structural contract — it checks one
  pattern (`from kaine.evaluation`), misses `import kaine.evaluation as ...`, and
  encodes the layering only implicitly.

The research work keeps creating core components that legitimately need logic that
historically lived in evaluation (the JSONL sink, the privacy filter, the
sustained-distress detector, the welfare-count helper), so the line is crossed
often — and each crossing is a chance to slip and burn a full-suite run to find
out. The boundary is currently clean (we extracted `AsyncJsonlSink` →
`kaine/persistence`, `PrivacyFilter` → `kaine/privacy_filter`, the distress
detector → `kaine/lifecycle/welfare_signal`, `welfare_counts` →
`kaine/experiment`), but the convention is policed only by the slow grep.

## What Changes

- Adopt a structural **import-linter** (the `import-linter` dev dependency, or an
  equivalent AST contract checker) with explicit, declared layer contracts:
  - the **forbidden** contract: nothing under `kaine/` may import `kaine.evaluation`
    except `kaine/cycle/__main__.py` and `kaine/nexus/__main__.py` (the only seams);
  - capture the **broader real layering** while we're here (e.g. `kaine.modules`
    must not import `kaine.cycle`; `kaine.evaluation` must not import nexus
    internals; the boundary-neutral shared homes — `kaine/persistence`,
    `kaine/experiment`, `kaine/privacy_filter`, parts of `kaine/lifecycle` — depend
    on neither core-runtime nor evaluation).
- **Run it fast**: a pre-commit hook + a dedicated lightweight CI job (separate from
  the 8-minute pytest), so a violation fails in **seconds** with a precise
  "module X imports kaine.evaluation, forbidden by contract Y" message instead of a
  grep assertion buried in the full suite.
- **Codify the convention** in a short architecture doc enumerating the layers, the
  two allowed seams, and the existing shared-primitive homes — the first thing a
  contributor (human or agent) sees, so the extraction pattern is followed by
  default rather than discovered by failure.
- Keep (or fold into the contract) the existing grep test as belt-and-suspenders so
  the guarantee survives even if the linter config is removed.

## Impact

- New dev dependency (`import-linter`, free, pip — dev/CI only, never shipped to the
  entity runtime) + a contracts config (`importlinter`/`pyproject` section), a
  pre-commit entry, a CI step, and an architecture doc. No runtime code change, no
  behavior change.
- Converts a recurring ~8-minute discovery into a ~2-second one, and turns an
  implicit convention into an enforced, documented architectural contract — which
  is exactly the recurring footgun the sprint surfaced.
- Strictly additive to the existing boundary test; the boundary is currently clean,
  so the linter passes on adoption.
