## 1. Implementation

- [x] 1.1 Add a per-event relief by an explicit fraction to the drives, and relieve boredom by rho_eng with `own=True` on each intent other than rest whose `about_kind` is not `"felt"`
- [x] 1.2 Wire `[affect] boredom_engagement_relief` (default 0.5, validated in [0, 1]) through the constructor, the factory and `config/kaine.toml`
- [x] 1.3 Tests: engagement relieves boredom and counts own; novelty alone still counts other; a felt intent does not relieve boredom; a boredom goal ended by engagement completes; the sleep reset is unchanged; with the key at 0.0 behaviour is identical to the previous build
- [x] 1.4 Update `docs/09-modules/affect.md`
