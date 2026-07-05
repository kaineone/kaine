## 1. Fix + guard

- [x] 1.1 Add a test asserting `chronos` `DEFAULT_USER_INPUT_STREAMS` contains
      `module_stream("audio_in")` and not `audio.in.out` (fails first).
- [x] 1.2 Fix `DEFAULT_USER_INPUT_STREAMS` → `("audio_in.out",)` in
      `kaine/modules/chronos/module.py`.
- [x] 1.3 Full suite green; `openspec validate "fix-chronos-default-stream"`.
