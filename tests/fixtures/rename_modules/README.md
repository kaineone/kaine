# Fixture cases for rename_modules

Each subdirectory holds a `case.json`, a `before/` tree, and optionally an `after/` tree. `case.json` supplies CLI `args`, the expected exit code, expected moves, and report substrings to check. `before/` is the tracked file set of a tiny repository; `after/` contains only files that change content or move, at their new paths. Files absent from `after/` must be byte-for-byte identical to their `before/` copies. This directory is listed in `EXCLUDED_GLOBS`, so neither the codemod nor the guard visits it.
