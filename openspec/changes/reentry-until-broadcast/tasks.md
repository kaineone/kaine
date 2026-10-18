## 1. Implementation

- [ ] 1.1 Keep each active goal's drive event pending until a broadcast accesses it, checked on every broadcast against the coalition, the inhibition flag and the access threshold; then schedule the next re-entry `P_re` after the access
- [ ] 1.2 Publish due re-entries and republish pending events only on the module's own `P_Aff` timer updates, one copy per goal per update, at least `P_Aff / 2` after the previous copy, while the drive is at or above threshold; record every copy's entry id among the drive entry ids
- [ ] 1.3 Clear pending state on goal end, the sleep reset and restore; leave `concern_reentry_s = 0` bit for bit identical to the build before re-entry
- [ ] 1.4 Tests: a missed crossing and a missed re-entry recur on timer updates until accessed; broadcast-triggered updates publish none; an inhibited, below-threshold or absent copy does not count; the interval runs from the access; no copy younger than `P_Aff / 2`; stops on goal end, stall, sleep and restore; intents about a repeat are about a drive; 0 is identical to the build before re-entry
- [ ] 1.5 Update `docs/09-modules/affect.md` and the `config/kaine.toml` comment
