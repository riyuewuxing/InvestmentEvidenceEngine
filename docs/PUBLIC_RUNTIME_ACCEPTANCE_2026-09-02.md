# Public Runtime Acceptance — 2026-09-02

## Verdict

`PASS_WITH_EXPLICIT_WARNINGS`

This acceptance proves that the independent Public `riyuewuxing/InvestmentEvidenceEngine` can execute the real public-evidence contract and that the private `touzizhuanjia` consumer can independently verify and admit its artifacts.

It does **not** mean every upstream was healthy or that WARN evidence became PASS.

## Fixed provenance

- Subject repo: `riyuewuxing/touzizhuanjia`
- Subject commit: `ccfcc2896407cac052192391144bae2ddc9ca28a`
- Canonical Public Engine activation commit: `c55fcf744aacd71fb40214d408d790b369dc25a1`
- Public acceptance execution commit: `86887ff40fee3166629f6e14d7531fe9542cc266`
- Request SHA256: `a7993b6b05ea9d5e15580f5560962eb4d758462015b50c0cf7e8a3da713b5dd9`
- Result SHA256: `d1349e939235588a81f71cbcc41700b609780f07fbcad98132823221726ec5cd`

## Public Actions evidence

### Regression

- Run: `33536018264`
- Result: `SUCCESS`
- Scope: install + 13 tests + Ruff on Public standard GitHub-hosted runner.

### Provider health

- Run: `33536018282`
- Result: `SUCCESS`
- Gate: at least one market provider usable and SSE/SZSE/CSRC official-source token validation 3/3.

### Real company execution

- Security: `600519`
- Run: `33536165615`
- Workflow result: `SUCCESS`
- Engine result: `WARN`
- Artifact ID: `9811857918`
- GitHub artifact ZIP digest: `sha256:8c0bc02892747ad98a48f6df6a364b3ac5c35e0733bc5df62c413d83bd1c37fa`
- Declared evidence artifacts: `9`
- Missing after download: `0`
- SHA mismatch after independent byte re-hash: `0`

Operation status:

- MARKET_DATA: `WARN` — AKShare Eastmoney unavailable, AKShare/Sina fallback used; BaoStock cross-check still available.
- PRICE_ANALYTICS: `PASS`
- KLINE_RENDER: `PASS`
- COMPANY_EVENT_TIMELINE: `PASS`
- FUNDAMENTAL_HISTORY: `WARN` — PIT availability dates require separate validation for this non-PIT-current request.
- VALUATION_HISTORY: `PASS`
- INDUSTRY_MACRO: `WARN` — benchmark fallback available while some Eastmoney industry endpoints were unavailable.
- OFFICIAL_SOURCE: `WARN` — SSE and CSRC official fallback routes used; no official-source BLOCK.

## Private consumer verification

The downloaded Public artifact was not trusted by executor declaration alone. The private subject runtime exported from the fixed subject commit ran its own `admit_execution_directory()` against the actual downloaded files.

Result:

- Admission status: `WARN`
- `execution_verified=true`
- `artifact_integrity_verified=true`
- `admissible_for_decision=true`
- Blockers: `0`
- Admission EvidenceGraph SHA256: `a14c67b43169c44bd1a16b01c7c31a4cce2677228f5f17652aa7dd6fcbd224e5`

Commander structural binding was also exercised without making an investment recommendation:

- CommanderEvidenceSession: `WARN`, blockers `0`
- merged/Commander EvidenceGraph verify: `true`
- Commander graph SHA256: `866aba8a9ecbb8561e9270d8a8ab248141be28273caffa4f858ac92be30b471a`
- DecisionMemo conclusion: `null`
- `research_only=true`
- `execution_allowed=false`
- memo graph ID match: `true`
- memo graph SHA match: `true`

## Boundary conclusion

The architecture is now demonstrated end-to-end:

`private subject contract -> independent Public executor -> Public artifacts -> independent observed-byte hashing -> private EvidenceAdmission -> EvidenceGraph -> Commander structural binding`

The Public Engine remains a non-intelligent evidence/compute executor. No private portfolio/account state was sent to it, no investment recommendation was produced, and no broker execution capability was introduced.
