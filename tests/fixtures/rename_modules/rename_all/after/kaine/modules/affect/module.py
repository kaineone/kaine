# Affect module

"""Affect keeps the mood."""

AFFECT_STREAM = module_stream("affect")


class AffectModulator:
    name = "affect"


cfg = {}
cfg["affect"] = True

episodic_memory_store = None
x = supervisor.incident
# Configure SupervisorConfig here
