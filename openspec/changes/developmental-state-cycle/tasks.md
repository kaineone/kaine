## 1. Implementation

- [x] 1.1 Run the developmental state cycle in the sleep module, reusing the developmental-rest hold, with trigger `state_cycle`
- [x] 1.2 Gate fatigue sleeps and the hourly backstop off in the developmental phase, and leave both unchanged after maturation
- [x] 1.3 Remove the boredom-stall rest request from the affect and sleep modules, keeping the stall abandonment
- [x] 1.4 Persist the cycle's phase and elapsed entity time, and resume a rest cut by a restart
- [x] 1.5 Config defaults from Table A1 with validation; dashboard sleep-panel label
- [x] 1.6 Tests: cycle timing on a fake entity clock, no fatigue sleep in the phase, unchanged behaviour after maturation, a restart mid-rest and mid-awake, no rest request from the affect module, old snapshots restore, probes and welfare accounting through a rest
- [x] 1.7 Offline replay of the eleventh boot's series through the new cycle, reporting rests and rest share
- [x] 1.8 Docs: sleep, affect, sleep README, dashboard
