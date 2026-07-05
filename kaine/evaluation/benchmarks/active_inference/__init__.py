# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline AIF-vs-RL benchmark (KAINE Paper §6.3, §11).

The paper does not assume active inference is a general decision engine; it
makes a falsifiable claim and attaches this benchmark to it: Nous's bounded
discrete active-inference decisions are compared head-to-head with a
reinforcement-learning baseline matched on observation model and reward, over a
suite of bounded discrete tasks, reporting decision quality, sample efficiency,
and the *value of epistemic action*. The hypothesis under test is that active
inference's explicit information-value term yields better epistemic behaviour on
these bounded problems. A NULL result (matches but does not beat the baseline)
and a NEGATIVE result (underperforms) are both first-class, reportable outcomes.

Everything here is OFFLINE: synthetic discrete POMDPs, no bus, no intents, no
entity boot, no cognitive cycle. The active-inference agent reuses the *same*
pymdp engine core (:meth:`kaine.modules.nous.engine.PymdpEngine.infer`) the live
Nous module drives, so the benchmarked engine IS the live engine.
"""
