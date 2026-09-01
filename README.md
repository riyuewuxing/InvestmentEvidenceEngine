# InvestmentEvidenceEngine

Portable public-data evidence/compute executor for the `touzizhuanjia` Commander architecture.

This repository is the canonical Public `riyuewuxing/InvestmentEvidenceEngine` implementation.

It is intentionally isolated from private investment state and never checks out the private subject project.

## What the Engine is

A **non-intelligent executor** that:

- validates a sealed, public-data-only `ExecutionRequest`;
- fetches public market/company/rule evidence;
- performs deterministic calculations, replay, backtest and research-priority scans;
- renders evidence such as K-line charts;
- produces artifacts with SHA256 provenance;
- seals an `ExecutionResult`.

It does **not**:

- receive account holdings, cash, cost basis or real transactions;
- decide whether the user should buy, sell or hold;
- act as an LLM/agent;
- execute broker orders;
- have decision authority.

All contracts enforce `decision_authority=false`; external execution remains research-only.

## Implemented operations

All reserved operation kinds are connected to the dispatcher:

- `MARKET_DATA`
- `PRICE_ANALYTICS`
- `KLINE_RENDER`
- `COMPANY_EVENT_TIMELINE`
- `FUNDAMENTAL_HISTORY`
- `VALUATION_HISTORY`
- `OWNERSHIP_FLOW`
- `INDUSTRY_MACRO`
- `OFFICIAL_SOURCE`
- `PIT_REPLAY`
- `FACTOR_COMPUTE`
- `BACKTEST`
- `OPPORTUNITY_SCAN`
- `PORTFOLIO_MATH`
- `TEST_SUITE`

Important semantics:

- market acquisition supports resilient public upstreams and provider cross-checking;
- historical fundamental/ownership availability limitations are surfaced rather than guessed;
- `OPPORTUNITY_SCAN` means research-priority ranking, not return prediction or trade signal;
- `PORTFOLIO_MATH` is generic/synthetic compute only, never a real private-account input path;
- `TEST_SUITE` uses a command allowlist.

## Workflows

`.github/workflows/` contains:

- regression testing;
- provider-health probing;
- request execution.

`execute-request.yml` accepts:

- committed `requests/*.json`;
- manual `workflow_dispatch`;
- `repository_dispatch` event type `execute-evidence-request`.

For `repository_dispatch`, the request is supplied as `client_payload.request`. The workflow reconstructs the JSON and revalidates:

- request SHA256;
- `private_data_included=false`;
- every operation `public_data_only=true`;
- request/operation `decision_authority=false`.

Treat every Public repository input/log/artifact as potentially public. Never put private portfolio or account state in the payload.

## Current validation status

The bootstrap has already passed a **pre-public** GitHub-hosted regression from the private subject repository:

- code commit `98d0d4db7ffb0461797fd1deb376dd2279d68914`
- workflow run `33530546493`
- install / compile / 13 tests / Ruff: PASS.

It also passed a real `600519` pre-public vertical slice:

- commit `af7f9c349c3cb032b51ac127c29e708eddbc7809`
- workflow run `33531002571`
- real public evidence acquisition and rendering;
- 9 declared artifacts re-hashed by the private consumer;
- 0 missing, 0 mismatch;
- EvidenceAdmission and EvidenceGraph verified;
- CommanderEvidenceSession built without blockers;
- structural DecisionMemo bound to the verified graph with `conclusion=null`.

The executor result deliberately remained `WARN` where upstream degradation or PIT limitations existed. WARN is not rewritten as PASS.

The independent Public repository now exists. Public runner acceptance is executed and recorded separately from the historical pre-public baseline; see `PROJECT_STATE.md` and `PROJECT_ROADMAP.md`.

## Public acceptance

Public activation requires:

1. regression and provider health on the Public standard runner;
2. a real-company vertical slice;
3. private-project consumption that re-hashes actual Public artifact bytes;
4. distinct subject and executor repository/commit provenance;
5. a pinned release/tag after acceptance.

Do not solve Public compute by giving a Public workflow credentials to clone the private `touzizhuanjia` repository.
