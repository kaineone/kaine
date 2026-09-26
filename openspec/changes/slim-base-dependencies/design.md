# Design — `slim-base-dependencies`

## The table (`kaine/extras.py`)

`REQUIREMENTS: dict[str, tuple[Requirement, ...]]` maps a module or service name to what it needs, where `Requirement(import_name, extra)`:

| Name | Needs (import → extra) |
|---|---|
| soma | torch → core, ncps → core |
| chronos | torch → core, ncps → core |
| mnemos | sentence_transformers → memory; plus qdrant_client → memory when `[mnemos].backend = "qdrant"`, or sqlite_vec → memory-edge when `backend = "sqlite_vec"` |
| empatheia | qdrant_client → memory and sentence_transformers → memory, when `[empatheia].backend = "qdrant"` |
| hypnos | sentence_transformers → memory, when its consolidation embedder is enabled (read the existing config key) |
| topos | torch → core, transformers → vision, PIL → vision, cv2 → vision |
| audition | only when capture is enabled: sounddevice → audio, webrtcvad → audio; av → audio in playlist mode |
| nous | pymdp → reasoning, jax → reasoning (the real engine) |
| phantasia | jax → worldmodel, when `backend = "dreamer"` (read the existing key) |
| nexus (service) | fastapi → nexus, uvicorn → nexus, jinja2 → nexus |
| soma GPU telemetry | pynvml → nvidia, optional: a warning, not an error, because Soma already degrades without it |

- `check(config) -> list[Missing]` uses `importlib.util.find_spec`, so nothing heavy is imported. `format_missing(list) -> str` names each module, the missing import and the `pip install "kaine[<extra>,...]"` line that fixes it.
- `build_registry` calls `check` for the enabled modules before constructing any of them and raises `ConfigurationError` with the formatted message. The cycle entrypoint already turns that into a clean exit with no traceback.
- The facts in the table are verified against the code by a test: for each row, the module's source imports that name. The test parses the import statements, so the table cannot drift silently.

## pyproject

- Base and extras are as in the proposal. `full` lists the runtime extras by name (`kaine[core,memory,memory-edge,nexus,nvidia,vision,audio,reasoning,worldmodel,oscillator]`), minus `training` and the InternVideo extras, which stay opt-in as today.
- Version pins move with the packages, unchanged.

## Installers

- `install.sh`/`install.py`: `--extras LIST` (default `full`). The torch wheel logic runs only when `core` (or `full`) is selected. The post-install verification imports torch only in that case, and otherwise imports `kaine.boot` and runs `kaine.extras.check` against the shipped config to report what the chosen extras support.
- The pip line becomes `pip install -e ".[test,<extras>]"`.
