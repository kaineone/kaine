## 1. Dependency registry + detection (`kaine/setup/dependencies.py`)
- [x] 1.1 `DepSpec` registry (redis/ollama/qdrant = command; speaches/chatterbox = guide)
- [x] 1.2 Real detection: `shutil.which` (binary) + TCP connect (running); `redis_port` override
- [x] 1.3 `implied_external_deps()` + `detect_dependencies()` (only needed deps)

## 2. Wizard step (`kaine/setup/__main__.py`)
- [x] 2.1 `_provision_dependencies`: report running; show+consent-run command deps; print guide deps
- [x] 2.2 Never install without consent; never crash on failure; `--defaults` shows but does not run
- [x] 2.3 Call it after `_install_extras`, before the summary

## 3. Installer + docs
- [x] 3.1 `scripts/install.sh` note that the wizard detects external services
- [x] 3.2 `docs/getting-started.md` dependency step (present-tense)

## 4. Tests (`tests/test_dependencies.py`)
- [x] 4.1 implied mapping; detect-only-needed; running-satisfied; redis-port override
- [x] 4.2 provisioning: running-not-offered; consent-runs; skip-without-consent; guide-never-runs; never-crashes; defaults-shows-not-runs
- [x] 4.3 Full suite green before PR
