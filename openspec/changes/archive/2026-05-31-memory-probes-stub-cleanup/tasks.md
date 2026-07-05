## 1. Pre-flight grep

- [x] 1.1 `git grep "reconstruction_accuracy" -- kaine/ tests/` —
      confirm zero references outside the function definition itself
      (one match expected: the definition in
      `kaine/evaluation/memory_probes.py`)

## 2. Removal

- [x] 2.1 Delete `reconstruction_accuracy` from
      `kaine/evaluation/memory_probes.py` (lines 45-50)

## 3. Verification

- [x] 3.1 `openspec validate memory-probes-stub-cleanup --strict`
- [x] 3.2 Full suite passes (no regression)
- [x] 3.3 `git grep "reconstruction_accuracy" -- kaine/` returns empty
- [x] 3.4 Commit (one-liner: "Remove dead reconstruction_accuracy stub")
- [x] 3.5 Merge + archive (no tag — too small to warrant one)
