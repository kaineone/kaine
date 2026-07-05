"""Vendored DreamerV3 RSSM world-model core (path b — faithful re-implementation).

See `UPSTREAM` for provenance, the pinned danijar/dreamerv3 commit, the MIT
notice, and the rationale for the self-contained re-implementation. This package
is imported only when KAINE's Phantasia module selects the real `dreamerv3`
backend, which requires the `[worldmodel]` optional extra (jax). The rest of the
test suite uses `FakeWorldModel` and never imports this package.
"""
