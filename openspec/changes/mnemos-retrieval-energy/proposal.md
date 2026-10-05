## Why

Mnemos stores and recalls, but it never publishes surprise. Under the complementary-learning-systems account the paper cites (McClelland, McNaughton and O'Reilly 1995), familiarity is a signal in its own right: how well the current content matches what memory holds.

Modern Hopfield retrieval (Ramsauer et al., arXiv 2008.02217) gives that signal directly. The retrieval energy of a query against stored patterns is low for familiar content and high for novel content (alternatives review 2026-10-05, §5.4).

**Design document only.** Nothing is built until the workspace-mediation ablation has run, because a new Mnemos signal adds a new competitor to the workspace.

## What Changes

A design for a content-free familiarity signal (retrieval energy) computed from the recall embedding Mnemos already makes (`mnemos-recall-and-vector-strip`), published as a scalar.

## Impact

- Code: none in this change.
- Licence: the reference library `ml-jku/hopfield-layers` is BSD-3 but unmaintained since April 2023. The computation is small enough to write directly.
