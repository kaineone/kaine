## Why

torch 2.15.0 was released. The offline suite's latest-torch step installed `torch torchvision` from the CPU index with no bound, got 2.15.0 and pinned it in the constraints file, which conflicts with the `torch>=2.9.1,<2.15` pin in pyproject's core extra. pip reports ResolutionImpossible, so every pytest job fails on every branch, main included.

## What Changes

- The latest-torch step reads the full torch requirement from pyproject's core extra, the way the minimum-torch step already parses it, and installs that requirement plus torchvision from the CPU index. pip picks the newest torch inside the declared range and a torchvision built against it.
- The cap is not raised. Moving to torch 2.15 is a separate decision.
- No other workflow, script or doc installs torch unbounded in this way (the other CPU-index mention is the minimum-torch step, which is exact).

## Impact

- `.github/workflows/tests.yml` only.
