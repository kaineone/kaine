# Proposal — `slim-base-dependencies`

## Why

`pip install kaine` pulls in torch, transformers, sentence-transformers, ncps, qdrant-client, pynvml, fastapi, uvicorn and jinja2 whatever the host is and whatever the entity uses. That puts gigabytes of CUDA-built wheels on hosts that cannot use them, and fails outright where manylinux wheels do not exist: Termux on Android, and 32-bit ARM. It is the first blocker of the portability program (phase 1). The operator wants one entity on a desktop, a Jetson Orin Nano Super and a Pixel 6a, and each host should install only what its modules need.

## What changes

- **The base install keeps only what every entity runs on:** `redis`, `pydantic`, `httpx`, `numpy`, `psutil` and `cryptography`. Encryption stays in the base because research runs fail closed without it.
- **New extras:**
  - `core`: `torch`, `ncps`. Soma and Chronos need it until the NumPy CfC (phase 2).
  - `memory`: `sentence-transformers`, `qdrant-client`.
  - `memory-edge`: `sqlite-vec`, for the file-backed memory store.
  - `nexus`: `fastapi`, `uvicorn[standard]`, `jinja2`.
  - `nvidia`: `pynvml`.
  - `vision`: gains `transformers` and `Pillow`, beside `opencv-python-headless`.
  - `full`: every runtime extra. This is the desktop default.
  - Existing extras (`audio`, `reasoning`, `worldmodel`, `oscillator`, `training`, `internvideo`, `test`) keep their meaning.
- **A missing extra fails loud and early.** A table maps each module and service to the imports it needs and the extra that provides them. At boot, `build_registry` checks the enabled modules against it and stops with one message naming every missing extra. That happens before any module is built, not as an import traceback mid-boot. `python -m kaine.nexus` does the same for `nexus`.
- **Installer.** `scripts/install.sh` and `install.py` install `.[full]` by default, and `--extras a,b,c` installs a chosen set instead. Their verification imports torch only when `core` is installed.
- **Docs.** `docs/getting-started.md` lists the extras and what each unlocks.

## Impact

- `pyproject.toml`, `scripts/install.sh`, `scripts/install.py`, a new `kaine/extras.py` with the table and the check, `kaine/boot.py` (call the check), `kaine/nexus/__main__.py` (call the check), docs.
- The desktop's install is unchanged: `full` equals today's set.
- CI keeps installing `.[test,full]`.
