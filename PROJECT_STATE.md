# PROJECT_STATE.md｜InvestmentEvidenceEngine 当前状态

更新时间：2026-09-02
Canonical repository：Public `riyuewuxing/InvestmentEvidenceEngine`
Canonical implementation activation：`c55fcf744aacd71fb40214d408d790b369dc25a1`
Accepted executor snapshot：`86887ff40fee3166629f6e14d7531fe9542cc266`
Subject acceptance snapshot：private `riyuewuxing/touzizhuanjia@ccfcc2896407cac052192391144bae2ddc9ca28a`

## 当前结论

`IMPLEMENTATION=COMPLETE`
`PREPUBLIC_RUNTIME=VALIDATED`
`PUBLIC_REPOSITORY=CANONICAL`
`PUBLIC_REGRESSION=PASS`
`PUBLIC_PROVIDER_HEALTH=PASS`
`PUBLIC_VERTICAL_SLICE=PASS_WITH_EXPLICIT_WARNINGS`
`PRIVATE_CONSUMER_ADMISSION=PASS_WITH_EXPLICIT_WARNINGS`

Public Engine 已经真实独立运行，不再依赖 private `touzizhuanjia` checkout。

## Public runtime evidence

- Regression run `33536018264`: SUCCESS
- Provider-health run `33536018282`: SUCCESS
- Real `600519` execution run `33536165615`: SUCCESS
- Public execution commit `86887ff40fee3166629f6e14d7531fe9542cc266`
- Request SHA `a7993b6b05ea9d5e15580f5560962eb4d758462015b50c0cf7e8a3da713b5dd9`
- Result SHA `d1349e939235588a81f71cbcc41700b609780f07fbcad98132823221726ec5cd`
- Public artifact `9811857918`, ZIP digest `8c0bc02892747ad98a48f6df6a364b3ac5c35e0733bc5df62c413d83bd1c37fa`
- 9 declared artifacts, 0 missing, 0 observed-byte SHA mismatch.

## Private consumer evidence

Private subject runtime from fixed commit `ccfcc289...` re-read the downloaded Public bytes and ran production admission code:

- status `WARN`
- execution verified
- artifact integrity verified
- admissible for decision
- blockers 0
- Admission EvidenceGraph SHA `a14c67b43169c44bd1a16b01c7c31a4cce2677228f5f17652aa7dd6fcbd224e5`

Commander structural binding also passed with `conclusion=null`, `research_only=true`, `execution_allowed=false` and matching graph ID/SHA.

## WARN is intentional, not failure masking

The accepted real run contains transparent upstream degradation:

- AKShare used Sina fallback while BaoStock remained available for cross-check;
- current financial evidence warns that historical PIT availability requires separate validation;
- some industry Eastmoney endpoints were unavailable, benchmark fallback remained available;
- SSE and CSRC official fallback routes were used.

There were no BLOCK/ERROR operations. WARN must remain visible in downstream reasoning.

## Canonical responsibility

This repo owns public evidence acquisition, deterministic compute, charts, research calculations, source validation and sealed artifacts. It owns no AI decision authority, private portfolio state or broker execution.

See `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md` for the acceptance record.

## 2026-11-24 — public visual QA infrastructure

Independent synthetic browser + native Windows screen capture and bounded log transport implemented under `visual_qa/`. Status `SYNTHETIC_CAPTURE_TRANSPORT_VALIDATED` at `853f39a94d69ce7fbb4b88a1e7714d97ca7ce76d`, public run `45369573507`: browser desktop, browser mobile, native Windows actual screen capture, all three decoded/rehashed/viewed. Current follow-up lint/receiver regression is separate; no private product validation. No private code/data checkout, no new investment worker, no change to accepted executor snapshot. See `docs/PUBLIC_VISUAL_QA.md`.


## 2026-11-26 — public valuation cutoff regression repair

`VALUATION_HISTORY` previously returned rows after as_of and marked the response PASS without historical-vintage evidence. Repaired with exact one-symbol/date input, strict provider date schema, date cutoff, duplicate-date fail-closed behavior, observed_at, and explicit WARN / pit_safe=false / decision_authority=false. Synthetic boundary tests added. Status at corrective implementation `01713f14cd9ffd6557a76909e3140522027cd2ff`: public regression run 45673568281 completed/success, 30 pytest tests passed, Ruff passed. A bounded public provider smoke is added to check the actual date schema and observed cutoff; no records are uploaded. Until its run completes, live-provider schema remains unverified; publication vintage, independent source check and private admission are not established. Historical accepted executor pin unchanged. No private code, account data, credentials, or private runner used.

## 2026-11-26 — market cutoff and public scan input binding

The September acceptance above is historical, not current main acceptance. The prior public universe control at b0e00504ad6ff39dd415abebf5c2b4f293840762 observed 5,580 raw / 5,579 valid rows and 20 research-priority candidates; no independent listing coverage, quote trade-date verification or PIT vintage was established.

- Actual listing control at eeff8ba004f5612e05d13925b5292b704fd90516, run 45808245082: BLOCK; BaoStock listing worker watchdog 45.007 seconds, no second snapshot request. Receipt SHA256 printed by runner 7d6cf4551968ffdf2355521ebee2b874faf7fe6943b082dc81613000fcec9103. No listing comparison or independent price evidence.
- Market data cutoff repair: one exact symbol, market-local scope, calendar-day history offset, strict bars, 30-second worker bounds, explicit historical-vintage WARN. Real public control at 11e9ccf57687b983b4a6d5fb5489a8ca6260e00a, run 45809117132: 38 Eastmoney rows, 2026-09-28 through 2026-11-25, requested cutoff 2026-11-25, BaoStock 30.007s WATCHDOG_TIMEOUT, local artifact hash MATCH, research WARN / single source. Raw provider bytes not retained. Same SHA regression 45809117088: 525 tests and Ruff success. Earlier valuation smoke 45808807999: WARN 2,158 retained rows, 1 excluded after cutoff, local rehash MATCH, no historical-vintage proof. Provider-health 45808808590: availability probe only, not same-session two-source verification.
- Scan attachment transport: require bound exact materialized public scan bytes, size, path, first-record digest/identity, matching request scope, explicit system research filter, preserve input bytes and recheck after execution. Old empty-input hash contract preserved. RESEARCH recognized solely as fail-closed BLOCK until genuine vintage and research-profile execution are supported; no claim of runtime Gate2 research acceptance. Initial regression 45809525855 found variable-shadow regression (6 failed / 527 passed); corrected at fabcd018918f490d24084c0efaf91f575683ea40 (533 pytest passed, Ruff identified formatting). Subsequent hardening includes output alias protection and actual scan-worker output fixture. Check latest main regression logs for final exact SHA; do not infer current runtime status from prior smoke.
- No new admission pin, no private runner, no private data or credentials, no live or simulated execution. No modifications to frozen prospective controls. Formal source provenance and original bytes, independent price/listing coverage, genuinely captured historical availability, research profile and private same-SHA dual-gate acceptance remain unresolved.
