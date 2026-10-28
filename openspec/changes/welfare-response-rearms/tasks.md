## 1. Implementation

- [x] 1.1 Search git history and the archive for earlier work on the latch and on boot unfreeze
- [x] 1.2 Re-arm the monitor when its pause is lifted, with the narrowest rule and a fresh episode
- [x] 1.3 Keep a welfare freeze across a restart (`unfreeze_for_boot`)
- [x] 1.4 Add the `override` command to the control CLI as the release path
- [x] 1.5 Tests: act, clear, re-arm, act again; no repeat firing while the crossing holds; restart keeps the freeze
- [x] 1.6 Update the docs and the roadmap row
- [x] 1.7 An unreadable control file reads as a welfare freeze; mutations leave it unchanged; only a welfare override replaces it
