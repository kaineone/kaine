## 1. Pins
- [x] 1.1 Compose CUDA, ROCm and CPU and the quadlet unit default to b11382 by digest; `.env.example` and the deployment docs say to pin by digest.
- [x] 1.2 The trainer converter moves to b11382 with the tarball SHA-256 (`ec72df2b…`).
- [x] 1.3 A test: every committed model-server image default is a digest, and the converter tag names the same build as the pins.

## 2. Settings
- [x] 2.1 Every organ command line (compose, quadlet) carries `--fit off -ngl <n>`, `--cache-ram <MiB>`, `-c <ctx>`, `-np <slots>` and `-ctk f16 -ctv f16`, with environment overrides that are validated as integers.
- [x] 2.2 A test: no committed definition passes `--slot-save-path`, and the compose and quadlet command lines agree.
- [x] 2.3 Real path: start the pinned organ on this host under the GPU lock and confirm it loads every layer on the GPU with the explicit flags. Stop it immediately afterwards. Without `-c`, fitting off allocated the model's full training context and the load failed out of GPU memory; with `-c 32768 -np 4` it loaded healthy (4 slots of 8192 tokens, about 4.1 GB of VRAM, 84 tokens/s), and `/props` reports `build_info` and `model_path`.
- [x] 2.4 A test runs the quadlet's integer validation for the context size and slot count.
