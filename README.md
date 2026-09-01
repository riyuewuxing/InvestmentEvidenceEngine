# InvestmentEvidenceEngine

Public-data evidence/compute executor for the private `touzizhuanjia` Commander architecture.

**Canonical Engine repository:** `riyuewuxing/InvestmentEvidenceEngine`  
**Accepted executor snapshot:** `86887ff40fee3166629f6e14d7531fe9542cc266`

This repository is intentionally isolated from private investment state and never checks out the private subject project.

## Role

The Engine is a **non-intelligent executor**. It validates sealed public-only requests, fetches public market/company/rule evidence, performs deterministic research compute, renders charts, hashes artifacts and seals an `ExecutionResult`.

It does **not** receive real account holdings/cash/cost basis/transactions, make BUY/SELL/HOLD decisions, act as an LLM/agent, or execute broker orders. `decision_authority=false` is part of the contract.

## Operations

All 15 reserved kinds are implemented and dispatched:

`MARKET_DATA`, `PRICE_ANALYTICS`, `KLINE_RENDER`, `COMPANY_EVENT_TIMELINE`, `FUNDAMENTAL_HISTORY`, `VALUATION_HISTORY`, `OWNERSHIP_FLOW`, `INDUSTRY_MACRO`, `OFFICIAL_SOURCE`, `PIT_REPLAY`, `FACTOR_COMPUTE`, `BACKTEST`, `OPPORTUNITY_SCAN`, `PORTFOLIO_MATH`, `TEST_SUITE`.

`OPPORTUNITY_SCAN` is research-priority ranking, not a return forecast. `PORTFOLIO_MATH` accepts only generic/synthetic/public-model inputs.

## Workflows

- `engine-regression.yml` — install/tests/Ruff;
- `provider-health.yml` — public provider and official-source health;
- `execute-request.yml` — committed request, manual dispatch, or `repository_dispatch: execute-evidence-request`.

Every request is revalidated for its SHA256, `private_data_included=false`, `public_data_only=true`, and `decision_authority=false` before execution.

## First independent Public acceptance

Completed on 2026-09-02:

- Public regression run `33536018264`: **SUCCESS**;
- Public provider-health run `33536018282`: **SUCCESS**, SSE/SZSE/CSRC official gate 3/3;
- real `600519` execution run `33536165615`: **SUCCESS**;
- executor commit `86887ff40fee3166629f6e14d7531fe9542cc266`;
- artifact ID `9811857918`, 9 declared evidence artifacts;
- independent observed-byte verification: **0 missing / 0 SHA mismatch**;
- private `touzizhuanjia` production admission: execution/integrity verified, admissible for decision, **0 blockers**;
- Commander structural binding verified with `DecisionMemo.conclusion=null`, `research_only=true`, `execution_allowed=false`.

The Engine result remained **WARN**, not fake PASS, because real upstream degradation was visible: AKShare used Sina fallback, historical PIT availability requires separate validation, some industry endpoints degraded, and official fallback routes were used. No BLOCK/ERROR remained in the accepted run.

See `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md`, `PROJECT_STATE.md`, `PROJECT_ROADMAP.md`, and `NEXT_SESSION_PROMPT.md`.

## Security / privacy rule

Treat every Public repository input, log and artifact as public. Never put private portfolio/account state in a request. The private project must independently re-hash downloaded artifact bytes before EvidenceAdmission; executor-declared hashes alone are insufficient.

## Next workstream

The first Public vertical slice is complete. The next major line is scale/governance: representative factor/backtest benchmarks, large-universe opportunity scanning, matrix/sharding decisions, provider schema-drift/backoff, data-license/artifact-retention policy, dependency/SBOM/security gates, and contract/version compatibility.
