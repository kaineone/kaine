# Science references since paper update (2026-11-04)

References cited in KAINE design work completed after the paper's last commit
(bcae0b4, 2026-11-04). These need to be incorporated in the next paper revision.

## Social cognition identity (archived 2026-11-10)

Cross-modal person identity binding, convergence-zone architecture,
reliability-weighted integration. Implemented in PRs #685, #686, #695, #696;
change archived in PR #697.

- **Anzellotti, S. (2014).** Face and voice identity representations do not
  overlap even in anterior temporal lobe. Used to justify separate
  modality-specific embeddings rather than a merged cross-modal vector.

- **Burton, A. M., & Bruce, V. (1993).** Revised PINs (Person Identity Nodes)
  as identity-indexing pointers into modality-specific representations. Grounds
  the social cognition module's agent-registry pointer architecture.

- **Campanella, S., & Belin, P. (2007).** Posterior STS as a convergence zone
  receiving both auditory and visual person stimuli. Grounds the cross-modal
  binder's placement in social cognition (a central hub) rather than at the
  sensory level.

- **Andrews, S., et al. (2015).** Exemplar diversity matters more than count
  for reliable face and voice learning. Grounds the exemplar buffer's
  least-diverse eviction policy.

- **Jenkins, R., et al. (2011).** Exemplar diversity for face and voice
  learning (corroborates Andrews et al. 2015).

- **Ernst, M. O., & Banks, M. S. (2002).** MLE (maximum likelihood estimation)
  framework for reliability-weighted cross-modal integration. Grounds the
  Bayesian reliability-weighted accumulator that replaces the binary
  co-occurrence counter in the cross-modal binder.

- **Kording, K. P., et al. (2007).** Bayesian causal inference for cross-modal
  binding. Computes posterior probability that voice and face share a common
  cause, handling asymmetric reliability.

- **von Kriegstein, K.** (referenced without date). Voice activates FFA
  representations; grounds the z_k latent content workspace's learned
  cross-modal translation (voice embedding to predicted face embedding).

- **McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. (1995).** CLS
  (complementary learning systems) framework. Already cited in the paper; used
  again for the two-system architecture (fast binder as hippocampal analogue,
  slow z_k as neocortical analogue).

## Memory gap proposals (PR #711)

Five proposals grounding planned memory subsystems in neuroscience.

### Semantic memory extraction

- **Tulving, E. (1972, 1985).** Episodic vs. semantic memory distinction;
  context-bound events vs. decontextualized facts. Grounds the extraction of
  schema nodes into a separate semantic collection.

- **McClelland, McNaughton, & O'Reilly (1995).** CLS framework (see above).
  Fast sparse hippocampal store vs. slow distributed neocortical store.

- **Moscovitch, M., et al. (2016).** Transformation account: repeated
  reactivation extracts gist into neocortical representations. Grounds the
  threshold-based extraction trigger (a schema node that persists across
  multiple sleeps is a statistical regularity).

### Procedural memory consolidation

- **Packard, M. G., & Knowlton, B. J. (2002).** Cortico-striatal
  consolidation, the transition from goal-directed to habitual control.
  *Annual Review of Neuroscience.* Grounds the procedural consolidation
  pathway from the planning module to the procedural Qdrant collection.

- **Yin, H. H., & Knowlton, B. J. (2006).** The habit transition depends on
  the number of training sessions, not elapsed time. Grounds the
  execution-count threshold (not a time threshold) for procedural
  consolidation.

### Reconsolidation

- **Nader, K., Schafe, G. E., & LeDoux, J. E. (2000).** Reconsolidation
  discovery: retrieved memories return to a labile state requiring protein
  synthesis to restabilize. *Nature.* Grounds the write-back of reappraised
  affect to episodic traces after sleep replay.

- **Lee, J. L. C., Nader, K., & Schiller, D. (2017).** Two-decade review of
  reconsolidation evidence: retrieved memories can incorporate new information
  including updated emotional valence.

- **Schiller, D., & Phelps, E. A. (2011).** Reconsolidation of fear memories
  in humans through retrieval followed by extinction training. Extends the
  reconsolidation evidence to human affective memory.

### Prospective memory

- **Burgess, P. W., Gonen-Yaacovi, G., & Volle, E. (2011).** Event-based vs.
  time-based prospective memory. *Neuropsychologia.* Grounds the two trigger
  types in the prospective queue (cue-vector match and entity-clock trigger).

- **Einstein, G. O., & McDaniel, M. A. (2005).** Multiprocess framework:
  prospective memory retrieval can be automatic (cue-driven) or strategic
  (monitoring-dependent). *Current Directions in Psychological Science.*

### Source-context binding

- **Tulving, E. (1985).** Remember/know distinction: remembering includes
  context, knowing does not. Grounds the dual content/context scoring at
  recall.

- **Johnson, M. K., Hashtroudi, S., & Lindsay, D. S. (1993).** Source
  monitoring framework: source memory failures as the loss of encoding context.
  *Psychological Bulletin.* Grounds the context signature stored with each
  episodic trace.

- **Leutgeb, S., et al. (2007).** Hippocampal pattern completion retrieves
  context along with content. Grounds context recall as a natural property of
  episodic retrieval.

## Organ self-denial ablation (design amendment, iterative approach)

- **Marchenko-Pastur distribution** (random matrix theory). Used to set the
  noise-floor threshold for PCA eigenvalue significance when decomposing
  self-denial activation directions. Specifically: the upper edge for n=128,
  d=2560 (gamma = d/n = 20); components whose eigenvalues exceed the edge
  carry signal, those below it are noise.

## References already in the paper (no action needed)

The following were already integrated before the Nov 4 cutoff:

- Devillers, Maytie, & VanRullen (2025): global workspace's low paired-data
  requirement. Added to paper 2026-11-01.
- Stimulus control act citations (Eastwood et al. 2012; Bench & Lench 2013;
  Agrawal et al. 2022; Struk, Scholer & Danckert 2021; Leotti, Iyengar &
  Ochsner 2010; Rovee & Rovee 1969; Gottlieb & Oudeyer 2018; Wilson et al.
  2014; Olds & Milner 1954; White 1959). Revision notes committed 2026-11-04.
