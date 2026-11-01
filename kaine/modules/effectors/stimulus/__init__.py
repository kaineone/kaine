# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulus control: the entity's bounded act on its own programme.

Held component (openspec change ``stimulus-control-act``): off in the shipped
configuration, and off builds none of this, so a run is bit-identical to a
build without it. The pieces, each imported from its own submodule:

- :mod:`.config`: the ``[stimulus_control]`` section, the declared actions and
  the bounds;
- :mod:`.programme`: the programme's channels and the seekable shared clock;
- :mod:`.controller`: the in-process control port and the feed wrappers;
- :mod:`.records`: the per-viewing welfare record and readout;
- :mod:`.effector`: the ``stimulus`` effector and its bounds;
- :mod:`.runtime`: the per-boot object that ties them to the effectors module,
  the stage-M act source and the affect credit window.
"""
