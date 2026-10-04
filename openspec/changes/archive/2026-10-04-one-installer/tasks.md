## 1. Image build
- [x] 1.1 `kaine.wheel_index`: `IMAGE_INDEX_BY_FLAVOR`, `image_index`, `torch_requirement`, and the `--image-index` and `--torch-spec` flags.
- [x] 1.2 The Dockerfile's runtime and trainer stages run those flags from a standalone copy.
- [x] 1.3 Check: each flavor gets the same index and torch requirement as before.

## 2. Retire the Python installer
- [x] 2.1 Remove `scripts/install.py` and its parity test; drop the `install.py` cases from the installer tests.
- [x] 2.2 Docs and specs describe one installer.

## 3. Tests
- [x] 3.1 The image index table, torch requirement parsing, and a simulated build stage with only the two modules and pyproject present.
