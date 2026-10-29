## 1. Prose

- [x] 1.1 Replace "harness" in `docs/`, `openspec/specs/` and `.github/ISSUE_TEMPLATE`.
- [x] 1.2 Replace it in comments, docstrings and strings in `kaine/`, `tools/` and `tests/`.
- [x] 1.3 Update the one docs anchor that carried the old heading.

## 2. Checks

- [x] 2.1 `grep -rni harness` over the scope leaves only identifiers, file names and paths.
- [x] 2.2 Run the docs, style and edited test files through `pytest-safe.sh`.
