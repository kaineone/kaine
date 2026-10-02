## 1. Changes
- [x] 1.1 Boot: `organ_adapter` with a backend other than `job_queue` raises `VoiceAlignmentConfigError`.
- [x] 1.2 `SubprocessVoiceTrainer.train`: after an accepted result, dispatch the hot swap (mode, adapter output dir, adapter path, reload URL, service unit); log and keep the promotion on failure; carry the status in the result metadata.
- [x] 1.3 `run_with_organ_window(..., trainer_backend=...)`: no bracket for `job_queue`; boot passes `voice_config.trainer_backend`.

## 2. Tests
- [x] 2.1 Each refused combination raises at boot; `job_queue` + `organ_adapter` and every other mode with each backend boot.
- [x] 2.2 A subprocess run that reports an accepted adapter calls the hot swap once with the promoted path; a rejected run does not; a raising hot swap leaves the result accepted.
- [x] 2.3 With `job_queue`, `run_with_organ_window` neither unloads nor reloads and reports the skip reason; with `reload_endpoint` and one GPU it still brackets.
- [x] 2.4 Mutation-check each.

## 3. Docs
- [x] 3.1 Voice-alignment page: which hot-swap modes each backend supports.
