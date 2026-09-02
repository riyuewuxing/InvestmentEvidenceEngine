# E6 Scale / Governance Runtime Acceptance

Date: 2026-09-02
Repository: Public `riyuewuxing/InvestmentEvidenceEngine`
Work branch: `e6/scale-governance`

## 1. Acceptance conclusion

`E6_CORE_SCALE_GOVERNANCE = PASS_WITH_EXPLICIT_SCOPE_LIMITS`

This acceptance proves the deterministic research-compute path can execute representative
synthetic workloads through the real `ExecutionRequest -> execute_request -> ExecutionResult`
contract, that deterministic matrix sharding works, that provider/schema monitoring and bounded
official-source retry are active, and that security/SBOM gates are operational.

It does **not** claim a live full-A-share discovery scan has been benchmarked. That remains a
real-market product scenario gate and must not be inferred from the synthetic capacity test.

## 2. Final branch regression

Code/security snapshot: `b67c485d6c37b8b6e92bd44509ec5cec117b4512`

- Engine regression run: `33619173573` — SUCCESS
- Pytest: PASS, 19 tests
- Ruff: PASS

The preceding retry implementation was also exercised by provider-health run `33618698768`.

## 3. Research compute benchmark

Workflow run: `33618492904` — SUCCESS
Benchmark code snapshot: `f4b72ed20de1afdf960cb72f0837937acd889650`

All six matrix jobs succeeded:

- baseline: 20,000 factor/backtest rows + 6,000 synthetic scanner rows;
- representative: 50,000 factor/backtest rows + 6,000 synthetic scanner rows;
- shard 0..3: 20,000 factor/backtest rows per job + a 12,000-row synthetic universe partitioned
  deterministically into four 3,000-row scanner shards.

### Observed representative metrics

| Profile | Factor/backtest rows | Scanner universe | Elapsed | Max RSS | Result |
|---|---:|---:|---:|---:|---|
| baseline | 20,000 | 6,000 | 0.411 s | 153,924 KiB | PASS |
| representative | 50,000 | 6,000 | 0.948 s | 242,796 KiB | PASS |
| shard-0 | 20,000 | 3,000 of 12,000 | 0.406 s | 147,828 KiB | PASS |

Every observed profile returned PASS for `FACTOR_COMPUTE`, `BACKTEST`, and `OPPORTUNITY_SCAN`.
The remaining three shard jobs also completed successfully in the same matrix run.

Key compact-artifact digests:

- baseline artifact `9841928068`: `sha256:ab852bd74115214f92253e7cfd1e78ca524eff9c4d8d635b727e7a5303dee553`
- representative artifact `9841928303`: `sha256:10732f9ae78f59ef7360a9e780fb237febc544ea37959b5b183df797d8800e0b`
- shard-0 artifact `9841930994`: `sha256:bcc8fe11dd64b3be337ae48161df67189abdc1346d6ad1a59070387b19235a91`

The benchmark intentionally deletes large generated input records before artifact upload and
retains compact benchmark evidence only.

## 4. Provider health, schema fingerprint, and retry evidence

Provider-health run: `33618698768` — SUCCESS
Artifact `9842115519`: `sha256:56fc49a730beced015c1807487b91cd51e8328f3f1ee53198485c324125d5519`

Observed market health during that run:

- AKShare primary attempt: BLOCK due to upstream connection abort;
- BaoStock: PASS, 33 rows;
- BaoStock normalized OHLCV schema: PASS;
- observed schema fingerprint:
  `72e44226bf43fa0daaf039da4821dc7e1bab991e51b70f26702bde63cdab0138`.

This is an observational fingerprint, not an automatically promoted forever-baseline.

Official sources: 3/3 PASS.

- SSE resolved through an official fallback after several official routes were unavailable;
- SZSE resolved from its official static PDF without fallback;
- CSRC recovered after one timeout retry and then passed token/content validation.

The retry layer is bounded. HTTP 403 is not endlessly retried; transient timeout/network and
selected 4xx/5xx statuses are retried, and retry/fallback history remains visible in evidence.

## 5. Security / supply-chain evidence

Final security run: `33619173578` — SUCCESS
Final artifact `9842203475`:
`sha256:011cc30a0b210b7792f6464455727411df719db9467282ad4de829f45dd1426e`

Final evidence inspection:

- untriaged secret findings: **0**;
- `pip-audit` exit code: **0**;
- dependency vulnerabilities: **0**;
- audited dependencies: **94**;
- CycloneDX SBOM components: **94**.

An earlier baseline correctly exposed two issues before the hard gate was enabled:

1. `request_sha256` in a public example was classified as a high-entropy string; this is a known
   public integrity hash field and is now excluded by field semantics rather than ignoring the
   whole example/request surface;
2. runner `setuptools 79.0.1` was flagged for `CVE-2026-59890 / PYSEC-2026-3447`; the security
   workflow now upgrades to `setuptools>=83` before the hard audit gate.

The final security workflow uploads evidence first, then requires zero untriaged secret findings
and zero dependency vulnerabilities.

## 6. Data / artifact governance

Implemented policy:

- bulk raw provider data remains transient runner state;
- no committed market caches;
- ordinary public evidence artifact retention <= 7 days;
- scale benchmark artifact retention <= 3 days;
- compact derived metrics/hashes/provenance/charts are preferred;
- provider package license is not treated as automatic permission to republish underlying data;
- unclear raw-data redistribution rights default to not approved;
- private tokens/account state remain forbidden in the Public repository.

See `docs/DATA_LICENSE_AND_RETENTION_POLICY.md`.

## 7. Compatibility governance

The Engine now has an explicit contract compatibility matrix in
`docs/CONTRACT_COMPATIBILITY.md`.

Breaking changes include request/result hash semantics, field removal/rename, artifact integrity
semantics, or PIT semantics. The `public_data_only=true` and `decision_authority=false` invariants
are not permitted to be relaxed as compatibility changes.

## 8. Remaining scope before product-level freeze

Not yet accepted as complete:

- live real full-A-share discovery/scanner throughput with actual public market inputs;
- reviewed persistent schema baseline promotion/alerting across multiple provider snapshots;
- Git tag/release surface if/when a write tool is available.

These do not invalidate the E6 core capacity/governance acceptance, but the live discovery case
must be exercised during product-level V2 acceptance before claiming universal production
coverage.
