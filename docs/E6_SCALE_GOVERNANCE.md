# E6 Scale and Governance Design

Updated: 2026-09-02

## Goal

Scale the Engine without changing its role. The Engine remains a non-intelligent public-data
executor with `decision_authority=false`.

## Benchmark contract

The benchmark must use the same `ExecutionRequest -> execute_request -> ExecutionResult` path
as production. It may generate deterministic synthetic records inside the runner because the
purpose is capacity/contract validation, not an investment conclusion.

Profiles:
- baseline: 20k factor/backtest rows + ~6k-asset scanner;
- representative: 50k factor/backtest rows + ~6k-asset scanner;
- sharded: 12k-asset universe partitioned deterministically into four matrix shards.

Recorded metrics:
- elapsed wall time;
- process max RSS;
- operation statuses;
- request/result hashes;
- executor repo/commit;
- shard dimensions.

Large synthetic input requests are deleted before artifact upload. Only compact benchmark
evidence is retained.

## Sharding rule

For independent cross-sectional work, partition by a deterministic asset index/hash and record:
`shard_index`, `shard_count`, total universe size and rows in shard. Never silently combine
results from different executor commits or different request schemas.

## Schema drift

Normalized OHLCV is a strict interface:
`date, open, high, low, close, volume` required; `amount, turnover` optional.

- missing required column -> BLOCK;
- extra normalized column -> WARN;
- fingerprint drift -> WARN until reviewed;
- baselines are never automatically promoted.

## Backoff / degradation

Retry is bounded and explicit. A retry does not erase the fact that an upstream failed.
Fallback/retry histories should remain visible in evidence. Exhausted mandatory sources remain
BLOCK; optional/secondary source loss may be WARN according to the operation contract.

## Security / supply chain

The weekly security workflow produces:
- secret-scan report;
- dependency snapshot;
- CycloneDX SBOM;
- pip-audit report and exit code.

Initial policy is evidence-first for dependency CVEs: findings are surfaced and triaged rather
than automatically breaking every run. Secret leakage remains a hard failure. A later policy can
promote selected severity/exploitability classes to BLOCK after the baseline is known.

## Artifact policy

- ordinary public evidence: <= 7 days;
- scale benchmark evidence: <= 3 days;
- no committed market caches;
- no private state, tokens, account data, or broker information;
- compact derived outputs preferred over raw provider dumps.
