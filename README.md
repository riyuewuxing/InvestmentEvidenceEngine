# InvestmentEvidenceEngine

Public-data evidence/compute executor for the private `touzizhuanjia` Commander architecture.

**Canonical Engine repository:** `riyuewuxing/InvestmentEvidenceEngine`

This repository is intentionally isolated from private investment state and never checks out the private subject project.

## Role

The Engine is a **non-intelligent executor** that validates sealed public-only requests, fetches public market/company/rule evidence, performs deterministic research compute, renders charts, hashes artifacts, and seals `ExecutionResult` objects.

It does **not** receive real account holdings/cash/cost basis/transactions, make BUY/SELL/HOLD decisions, act as an LLM/agent, or execute broker orders. Contract invariants remain `public_data_only=true` and `decision_authority=false`.

## Operations

All 16 reserved kinds are implemented and dispatched by the accepted V2-M5 Gate1 executor pin:

`MARKET_UNIVERSE`, `MARKET_DATA`, `PRICE_ANALYTICS`, `KLINE_RENDER`, `COMPANY_EVENT_TIMELINE`, `FUNDAMENTAL_HISTORY`, `VALUATION_HISTORY`, `OWNERSHIP_FLOW`, `INDUSTRY_MACRO`, `OFFICIAL_SOURCE`, `PIT_REPLAY`, `FACTOR_COMPUTE`, `BACKTEST`, `OPPORTUNITY_SCAN`, `PORTFOLIO_MATH`, `TEST_SUITE`.

`OPPORTUNITY_SCAN` is research-priority ranking, not a return forecast. `PORTFOLIO_MATH` accepts only generic/synthetic/public-model inputs.

`MARKET_UNIVERSE` acquires and normalizes a public A-share candidate universe through AKShare's
Eastmoney spot endpoint, with one bounded Sina fallback. It emits compact `records` for downstream
`OPPORTUNITY_SCAN` dependencies; it never emits advice, forecasts, or portfolio weights. Gate1
accepted executor `1161a8a91657b4d1e4719e513025956b1720938c` is `PASS_WITH_EXPLICIT_WARNINGS`;
V2-M5 overall remains `ACCEPTANCE_PENDING`. The final remote run had an AKShare primary failure,
successful paged Sina fallback, a 5555-row universe report with `WARN`, unavailable listing
cross-check, and unknown quote date; downstream scan was `WARN` with 20 candidates and 2 rules.
The preceding monolithic Sina `JSONDecodeError` was fixed by bounded paged retries. See
`docs/V2_M5_GATE1_RUNTIME_ACCEPTANCE_2026-09-04.md` for immutable run and artifact evidence.

## Current accepted state

### First independent Public vertical slice

- Public regression run `33536018264`: SUCCESS;
- Public provider-health run `33536018282`: SUCCESS, official source gate 3/3;
- real `600519` execution run `33536165615`: SUCCESS;
- first accepted executor commit `86887ff40fee3166629f6e14d7531fe9542cc266`;
- artifact ID `9811857918`, 9 declared artifacts;
- private observed-byte verification: 0 missing / 0 SHA mismatch;
- private production admission: verified/integrity verified/admissible, 0 blockers;
- Commander structural binding: `conclusion=null`, `research_only=true`, `execution_allowed=false`.

### E6 scale/governance core

- final E6 regression run `33619173573`: SUCCESS, 19 tests + Ruff PASS;
- research-compute benchmark run `33618492904`: all six matrix jobs PASS;
- provider/schema/retry run `33618698768`: SUCCESS, official sources 3/3;
- final security hard gate run `33619173578`: SUCCESS;
- final security evidence: 0 untriaged secrets, 0 pip-audit vulnerabilities, 94 audited dependencies, 94 CycloneDX components.

### V2-M5 Gate1 runtime acceptance

- accepted executor: `1161a8a91657b4d1e4719e513025956b1720938c`;
- subject commit: `c4525244b250042e360b3cd55f3657ca89a1a5d6`;
- Gate1: `PASS_WITH_EXPLICIT_WARNINGS`;
- M5 overall: `ACCEPTANCE_PENDING`;
- final Actions: Engine `33852576973`, Execute `33852576917`, Provider `33852576932`, Security `33852576906`, all SUCCESS;
- the Research benchmark `33849724972` succeeded on earlier executor `1d3e09d` and is not a same-pin Gate1 result;
- Private admission of the actual bytes: `WARN`, verified/integrity verified/admissible; tamper case `BLOCK`;
- the later documentation commit is not the executor pin, and `main` remains `db41a018447977e2203aed61239892dfbefbe1ac`.

Representative formal request-path benchmark:

- 50,000 factor/backtest rows + 6,000 synthetic scanner rows: ~0.948s, 242,796 KiB max RSS;
- four-way deterministic sharding exercised on a 12,000-row synthetic universe.

These are **capacity benchmarks**, not investment performance and not proof of a live full-A-share scan. Real-market DISCOVERY remains a product-level acceptance case.

## Workflows

- `engine-regression.yml` — unit/regression + Ruff;
- `provider-health.yml` — market/official-source health + schema fingerprint;
- `execute-request.yml` — sealed request execution;
- `research-compute-benchmark.yml` — formal compute/sharding benchmark;
- `security-supply-chain.yml` — secret scan, pip-audit, dependency snapshot and CycloneDX SBOM.

`execute-request.yml` supports committed request JSON, manual dispatch, and `repository_dispatch: execute-evidence-request`; every request is revalidated for SHA256, `private_data_included=false`, `public_data_only=true`, and `decision_authority=false`.

## Governance

See:

- `AGENTS.md`
- `PROJECT_STATE.md`
- `PROJECT_ROADMAP.md`
- `NEXT_SESSION_PROMPT.md`
- `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md`
- `docs/E6_RUNTIME_ACCEPTANCE.md`
- `docs/E6_SCALE_GOVERNANCE.md`
- `docs/DATA_LICENSE_AND_RETENTION_POLICY.md`
- `docs/CONTRACT_COMPATIBILITY.md`

Bulk upstream data remains transient by default. Ordinary evidence artifacts are retained <=7 days and scale benchmark artifacts <=3 days. A provider package's software license is not treated as a blanket license to redistribute upstream datasets.

## Next product-facing work

The Engine now supports the private `touzizhuanjia` V2-M5 Gate1 product case. Remaining acceptance work is **M5 product freeze and follow-up governance**:

`real public universe -> public evidence/features -> OPPORTUNITY_SCAN -> compact artifacts -> private observed-byte EvidenceAdmission`.

Private account state must remain private throughout this flow.

## V2-M5 implementation status

`MARKET_UNIVERSE` is `IMPLEMENTATION_COMPLETE / LOCAL_TESTS_PASS / LIVE_PROBE_PASS_WITH_EXPLICIT_WARNINGS`;
Gate1 is `PASS_WITH_EXPLICIT_WARNINGS` and M5 overall is `ACCEPTANCE_PENDING`. The accepted executor
is `1161a8a91657b4d1e4719e513025956b1720938c`; the subject is
`c4525244b250042e360b3cd55f3657ca89a1a5d6`. The final remote run recorded AKShare primary failure,
paged Sina fallback success, 5555 rows with universe `WARN`, listing unavailable, quote date
UNKNOWN, and downstream scan `WARN` with 20 candidates and 2 rules. Private admission of actual
artifact bytes was verified/integrity verified/admissible with WARN; the tamper case BLOCKed. The
documentation follow-up commit is not the executor pin; `main` remains
`db41a018447977e2203aed61239892dfbefbe1ac`.
