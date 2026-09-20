# Attribution

Everything under `data/index/` and `data/answers/` is derived from the DAB
benchmark (DataAgentBench), a collaboration between UC Berkeley's EPIC Data Lab
and Hasura PromptQL:

- Repository: https://github.com/ucbepic/DataAgentBench.git at commit `0290945c2b38ccbe1ccec6f4765d078350291129`
- Paper: Ma, Shankar, Chen, Lin, Zeighami, Ghosh, Gupta, Gupta, Gopal and
  Parameswaran, *Can AI Agents Answer Your Data Questions? A Benchmark for
  Data Agents*, 2026. https://arxiv.org/abs/2603.20576
- Ingested: 2026-09-20T06:07:53Z by `dab ingest`

The index carries the question text, the ground-truth answers, the validator
source and the dataset descriptions of the 54 leaderboard
queries across 12 datasets, and normalised copies of the
14480 published answers committed upstream. No database file is
copied. The upstream repository publishes no licence file; this copy exists so
the explorer runs from a bare clone, and it is removed on request.
