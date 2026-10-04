## 1. Split
- [x] 1.1 Move every top-level definition of `kaine/boot.py` verbatim into the `kaine/boot/` package (errors, common, factories, perception_feed, security, registry, wiring, metrics).
- [x] 1.2 `kaine/boot/__init__.py` re-exports every name.
- [x] 1.3 Check: every definition's AST equals main's, exists once, and is importable from `kaine.boot`.

## 2. Guards
- [x] 2.1 Import contract: module factories are independent (adding a factory-to-factory import breaks it).

## 3. Tests and docs
- [x] 3.1 Patches of `build_registry`'s collaborators target `kaine.boot.registry`.
- [x] 3.2 Docs and the config comment point at each factory's new file; the contributing guide describes a factory file.
- [x] 3.3 The full suite passes.
