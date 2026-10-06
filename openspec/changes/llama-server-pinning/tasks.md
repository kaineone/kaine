## 1. Pins
- [x] 1.1 Compose CUDA, ROCm and CPU and the quadlet unit default to b11382 by digest; `.env.example` and the deployment docs say to pin by digest.
- [x] 1.2 The trainer converter moves to b11382 with the tarball SHA-256 (`ec72df2b…`).
- [x] 1.3 A test: every committed model-server image default is a digest, and the converter tag names the same build as the pins.

## 2. Settings
- [x] 2.1 Every organ command line (compose, quadlet) carries `--fit off -ngl <n>`, `--cache-ram <MiB>` and `-ctk f16 -ctv f16`, with environment overrides that are validated as integers.
- [x] 2.2 A test: no committed definition passes `--slot-save-path`, and the compose and quadlet command lines agree.
- [ ] 2.3 Real path: start the pinned organ on this host under the GPU lock and confirm it loads every layer on the GPU with the explicit flags. Stop it immediately afterwards.
