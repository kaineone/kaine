## 1. Fixes

- [x] 1.1 Topos uses fp16 only on CUDA, and emotion2vec runs in float32 on CPU. Real-path test: load the provisioned model on CPU under a float16 default dtype (reproducing the race), classify a short tone, and require no `inference_failed`. The test skips only when funasr or the model is absent.
- [x] 1.2 Topos weights resolve at use time. Test: under a non-default data root, the encoder looks in `<root>/state/models/...` and not in the working directory.
- [x] 1.3 The device-fallback warning names the returned device. Test with zero CUDA devices.
- [x] 1.4 Real-load guard: a tiny float16 checkpoint loaded through the InternVideo-Next loader and the DINOv2 encoder never sets the default dtype to float16. A control load without a dtype must show the flip, or the test skips.
