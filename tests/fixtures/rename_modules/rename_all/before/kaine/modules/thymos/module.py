# Thymos module

"""Thymos keeps the mood."""

THYMOS_STREAM = module_stream("thymos")


class ThymosModulator:
    name = "thymos"


cfg = {}
cfg["thymos"] = True

mnemos_store = None
x = spot.incident
# Configure SpotConfig here
