## 1. Fixes

- [ ] 1.1 emotion2vec in float32 on CPU, with a real-path test: load the provisioned model on CPU, classify a short tone, and require no `inference_failed`. The test skips only when funasr or the model is absent.
- [ ] 1.2 Topos weights resolve at use time. Test: under a non-default data root, the encoder looks in `<root>/state/models/...` and not in the working directory.
- [ ] 1.3 The device-fallback warning names the returned device. Test with zero CUDA devices.
