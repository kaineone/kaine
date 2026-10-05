## The signal

For a query embedding ξ and stored patterns X (the short-term entry embeddings that recall already caches, plus a bounded sample of episodic vectors from the same embedding space), the modern Hopfield energy is:

`E(ξ) = −β⁻¹ · logsumexp(β · Xᵀξ) + ½ ξᵀξ + const`

- Lower energy means more familiar.
- β is fixed per embedding space and recorded. It is not tuned during a run.
- The signal is normalised against a rolling window, like the other modules' prediction errors.

## Publication

`mnemos.familiarity` carries `{energy, normalised_energy}`: scalars only, no text, no vectors. It competes in the workspace like any other prediction-error signal. The `mnemos-recall-and-vector-strip` cache bounds the cost.

## Later options (not proposed)

- Surprise-gated encoding: store more readily when energy is high, borrowed as an idea from EM-LLM (ICLR 2025, MIT).
- HippoRAG 2 for semantic memory. Its default embedder is CC-BY-NC, so it would be replaced.

## Gate

The ablation first. Then an offline check that energy separates repeated from new content on a frozen synthetic memory store. Then a change that ships it off by default.
