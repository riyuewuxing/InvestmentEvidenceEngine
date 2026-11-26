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


## 2026-11-26 — raw-price research and exchange listing diagnostics

- Fixed public 600519 control 45811109136 at 8c5d52e13493ee800c7a3f0f6b05f7ce986cadd7: 459 same-date Tencent/Eastmoney unadjusted OHLC bars, max relative difference zero, Tencent 79,520 raw bytes parent rehash MATCH; date range 2025-01-02..2026-11-25. Retrospective fixed 20-session momentum diagnostic with chronological 261/85/87 intervals, four purged/embargoed, next-open pricing and 10/20/30bp one-way cost stress. No tuning, no historical PIT or actionable research admission; raw prices exclude distributions and actual account costs. At 10bp test momentum +9.7421% vs continuous holding +14.6630%. No vendor raw bytes persisted. Regression 45811109249: 547 tests + Ruff.
- Integrated Tencent as raw secondary OHLC only (not primary volume, not adjusted basis). Actual production run 45811432164 at 6e3b310e8fbbf3c3ab584ff83aaa336ef12bfd15: 38 matched bars, zero OHLC difference, cutoff 2026-11-25, request/result/artifact hashes verified. WARN remains for vintage and ultimate source independence. Regression 45811432571: 551 tests + Ruff. Historical capture now reuses existing modern Eastmoney alias adapter.
- Official current listing control 45811866080 initially BLOCK (SSE compact date format, SZSE worker failure). Follow-up 45812151759 at 5d12dbf988f3d4695ba83fefe34ddde59e22fca4 observed SSE main 1700 and STAR 619 records, declared totals match, zero duplicates/invalid/future-date exclusions, raw bodies rehashed MATCH. SZSE URLError, no HTTP status. Complete listing not verified, no conditional full scan executed. No blind retries or weakened coverage gate. Packet replay checks exact sealed request/result/manifest and materialized bytes; synthetic tests only, real candidate bytes still missing.
- Regression 45811866165: 557 passed + Ruff; 45812151799: 572 passed, 1 failure (literal millisecond regex escape). Corrected regex without loosening accepted date formats; verify final exact-SHA public regression. No accepted pin change, no private runner, no prospective settlement or private state disclosure.


## 2026-11-26 — disclosure-directory / exact candidate replay

- Actual public run 45813236403 at 905328b2b961d766584e7f0272d1559478e01b0c: CNINFO disclosure search directory, 593247 bytes parent SHA match; 6267 total, 5579 SH/SZ prefix records, not an official active-listing set. Sina 5580 raw / 5579 valid; 5222 SH/SZ intersection, zero snapshot-only, 357 directory-only. Official SZSE transport remains BLOCK, no complete-list or quote-vintage proof. Separate WARN scan 20 candidates; 6852-byte exact scan replay and materialized attachment MATCH. Raw bytes temporary only.
- Actual run 45813637777 at 96eb12e253acfdcfe6146adba3ffd6db24647685: same scan hash 78c57ea6630f5e81debebf6720e32f007bd7ebc3aec72a5ed62ad356ce806d65 and first-record hash 9ac88e48efd79b9c6bbf0f5651893be6c3d72b29db54fcb48852d1a896555e57. First candidate 000035, Sina/Tencent 459 common unadjusted OHLC, max relative difference zero, Eastmoney worker failed; Tencent 69781-byte parent rehash MATCH. Fixed chronological 261/85/87 intervals, 4 gaps, 20-session momentum vs continuous holding; at 10bp test -11.61% vs -15.55%. Current-cohort ex-post selection, not historical universe or PIT, no forecast validation or decision authority. Do not repeat unchanged.
- Regression 45813236361: 579 + Ruff; 45813637696: 587 pytest, Ruff import-order failure; 45813937509 at 5dd051f8614be2935924c3b4956d0170699f87d3: 596 + Ruff. Shared strict selector, bounded actual difference validation added; verify latest exact SHA regression before claiming final code tested. One-shot scan workflow now manual only; no repeated live run on lint/test maintenance.
- Formal RESEARCH remains BLOCK. No raw vendor redistribution, no private checkout or runner, no new admission pin. Frozen prospective receipt untouched.


## 2026-11-26 — actual issuer originals, adjustment vintages and cashflow
- Actual CNINFO four originals #45815738164 at 60e95df5a7a8a5a96f7e060ff8e26c13b9e96d34, all parent and temporary-file rehash MATCH; exact page extraction from annual 2024/2025, policy, H1 2026. Assets original 32084341383.18, adjusted 32067826798.82; parent equity 10892968839.23 -> 10758535847.11. Policy effective Jan 1 2026, not an availability timestamp.
- Actual SZSE mirrors and full 2025 report #45816184147 at 02f7b68e9a0d361fa72afea76b713a8ef5513a55. Two annual summaries exact original/page hash matches; annual2024 path day differs by one day across hosts. Full report 258 pages, 1564092 bytes, hash 8a4b4c31599c17aaefc440721c0ccb6752456dd334ed03b7af24df4a35eed99d, pages 108-109 consolidated cashflow reconciled to cent. OCF-capex 2024 -1313367580.77 / 2025 -917202868.12 CNY; proxy not FCFF/FCFE; not current valuation or decision.
- Actual CNINFO index #45816874081 at 1ed48cc7a51e80fed561d5b1e5e6cfa7f81aad7f: 28/30/18 rows, four exact ID/title/attachment matches; all four raw platform time fields local midnight, not first availability. First run #45816692378 failed before network due empty worker arg, fixed with entry-point regression.
- Actual Q1 #45817483420 at 0bcc3d71c301200b5a1b58408ef6ed357e2b0e5d: 615623 bytes, SHA256 44357cae92cac0a3bc960bdc586e9be9f4403beb5259a6a375f66b165541c21b, pp11/12/14. Same adjusted values already documented in Q1 dated 2026-04-29; no August-first or intraday sequence inference. Audited 2025-12-31 versus unaudited 2026-01-01 opening amounts; assets/liabilities/total equity reconcile. First Q1 #45817220326 failed before network (parent route KeyError); fixed and verified. No raw PDF/JSON persisted.
- Q3 discovery #45817381220 at 4e03d7ce3b11fd451ca8c40d8965316069b46945: 13 observed announcements in 2026-10-01..11-26, no title match, result BLOCK. No inference of absence of filing; no blind retry or older data substituted for latest.
- PIT_REPLAY cannot extend sealed request cutoff or shadow dependencies by inline data; actual dated receipt regressions reject historical cutoff, current chronology WARN only. Intermediate regression 609 PASS, 615 pytest + Ruff fail (fixed blank line), 625 PASS, 633 PASS, 637/638 PASS, 639 PASS + Ruff at 0bcc3d71c301200b5a1b58408ef6ed357e2b0e5d #45817483380. Final change adds no-match/invalid-path guard and manual-only one-shot workflows; verify final exact-SHA regression.
- No vendor redistribution or historical first-availability certification. RESEARCH still BLOCK, no accepted pin advance, no private checkout/runner, prospective frozen receipt untouched.
