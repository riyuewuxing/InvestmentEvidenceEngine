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

## 2026-11-26 — Q3 alias, comparative basis, and durable BLS archive
- Q3 search alias fix: 13-row exact same index body SHA 273059c1e6784650df6aa255f60498487e42926e6fe1cb198b13384c18326776, title 2026年三季度报告, one ID 1225635059. Actual 45819299420 at a07fed6cf78272d1f7303b72386eb25cc072abde: issuer and CNINFO 227029 bytes, identical SHA dedeb15450b3005cb8f509cf1d3409347a76170ae5c7e9c5f21de04645ea3639, p1/p2 actual extract. Q3 adjusted profit YTD growth original -1.66%, restated +1.10%. Original bytes temporarily verified, not redistributed. Platform midnight not proof first availability.
- Actual 45820428540 at 8fc05d2e135c0892876998d5a1ab9d207d550fa4: same exact Q3 SHA, 25 rows pp5–7/9–10, balance/cash reconciliation MATCH. Current ratio .6947/.6723, debt/assets 68.19%/65.84%, 2026/25 nine-month OCF minus cash capex -1200955306.02/-562895671.83 CNY; coverage 29.60%/46.88%. Not FCFF/FCFE or execution advice.
- SEC fixed filing metadata/concept control 45819702173 at 5dd7703d9c226b319841bb53f997ef4c601a9e4b blocked HTTP 403 before concept request; no retry/circumvention or source activation. 648 pytest + Ruff fail fixed. 650 pytest + Ruff pass #45820428245. 650/652 pytest passed but import-order lint failed #45820629772/#45820903535; import-order fix at 0401bcb3.
- Public-domain BLS only: original release #45820629764 and two later #45821037999 recovered actual log chunks, independently decoded and SHA256-rehashed, retained 3 content-addressed PDFs, total 1729312 bytes in public-evidence/sha256/. Exact source / prior observation / permission / blob receipts public-evidence/README.md. Chain +22000 -> -4000 -> -26000; not historical capture/PIT, same BLS upstream. Verify latest regression including offline real bytes; no rerun of one-shot live probes, all manual-only. No private account/runner, no accepted pin change, formal RESEARCH BLOCK, frozen prospective receipt unchanged.

## 2026-11-26 — SZSE aggregate, event sensitivity and compute integrity
- #45823975346/job139923212106 at e43fe9dedf41e1b3e46ceb8db1c80c4bfa21f97b: official SZSE Oct 2026 monthly HTML 9349 bytes SHA256 27cd7a23c4db59e04bfb7398e558408ce22788081ce0529681bbe9d79e453f53 parent rehash MATCH, observed 12:54:36.344735 UTC, 2908 listed companies, 1411 ChiNext, derived 1497 non-ChiNext. Not current A-share code count. Distinct HTTPS first page returned URLError (no HTTP status); no downgrade to HTTP, bulk pagination, or full-coverage promotion.
- #45824427520/job139924805681 at 80ebf5b34ddc6f9b59a46203848433ea195a6dbd actual 000035/510300, 2026-08-24..11-06 49 common raw closes, Sina and Tencent both assets MATCH, no failure. Predeclared Oct29/30 event conventions, fixed 30-return estimation and 5-session gap, 1/3/5 cumulative close-return differences respectively [-2.0298,-1.3255], [-1.8346,+0.4622], [-2.9246,+0.6234] percentage points. Same-source-pair variants agree. CAR ranges [-1.7233,-1.1070], [-2.0372,-0.8101], [-6.1015,-3.4546] percent. Unknown exact clock, independent original upstream, corporate-action coverage, total return and causality unverified; no raw vendor bytes retained. Not forecast/admission/decision.
- 7e8b85cbdefe3412c7ab6d86acdd16f5d6f29c38 generic existing factor/backtest input hardening: no missing return/weight/cost imputation, numeric and time order validation, first-fee drawdown, explicit annualization only, factor undefined preserved, no inline/dependency conflict. 8a82aaa87375e91d4d2987d00243fd58bbd9f44e adds cutoff guard and explicit ordered-row lookback basis; not a genuine PIT or execution model.
- #45825201392/job139927456322 at 06c5983e13851879659ceb7a82b7044cc9caa69b offline actual 3 retained BLS PDFs, declared-release views UNAVAILABLE/+22000/-4000/-26000; durable-observed 2025 cutoff UNAVAILABLE, first verified original +22000, final verification -26000. Explicit lineage rejects forks/missing predecessor/conflict and out-of-order capture. Verification stamps conservatively rounded up in 665cd041. No historical capture or complete revision universe claimed.
- Shared single-read bounded artifact parser read_verified_artifact; production public scan and input consumer now parse exact verified bytes rather than a second read; private shared blob synced. #45825688233 698 pytest PASS but Ruff import wrap FAIL; corrected #45826071699/job139930414222 704 PASS and Ruff. Earlier 655/658/682/693 + Ruff all passed. Final exact SHA run must be checked. One-shot live probes/manual offline replay now manual-only. Formal RESEARCH remains BLOCK, private dual gates NOT_RUN, no historical pin or frozen receipt changes, no private runner/checkout.

## 2026-11-26 — cash entitlement and identity / compute integrity (new session T01)
- Actual #45828673907/job139939371738 at d7061d91c4f49cfd258b927558af015519bf09f5: CNINFO 000035 original 110462 bytes SHA256 206b923f9f1e0d12b6e5b20d77dc3b39eb57058da141b5358c2dd49952d540af; SSE 510300 original 139671 bytes SHA256 c8ff747d02fa90db72320458c38249f73720b932d61b7e088f033583aab63992; parent/temporary rehash MATCH. Known gross cash .036/.123 CNY per unit, ex-date Aug20/Jan19, record dates Aug19/Jan16. Jan05-Aug31 160 session labels match schedule; both Sina/Tencent per asset MATCH. Full raw -14.590747%/-3.282411%; one known cash event reinvested at ex-close -13.917939%/-0.771592%; differences +.672808/+2.510820 pp. WARN only. No full corporate action universe, verified calendar coverage, vintage, raw retention, taxes/fees or actual cash timing proof. Stock declared date and delegated payment date reviewed on PDF p3 but initial runner only checked p1; fields explicitly distinguish provenance in follow-up. ETF first/second pages checked; no exact publication clock. Do not rerun just for flags. Live workflow manual-only.
- ae471f78b9611f3d465681d682c702e2b4da4137: all observation labels respect both cutoffs, mixed-time rank/zscore blocks, same-label cross section retained, nonfinite normalization blocked. #45829098604 732 passed + Ruff; intentional overflow warning.
- BSE official mapping and pilot notices: #45829363865/job139941756170 at 4e84c0919b1db31479c3369e37ae46f195ff87f9 all four HTTPS routes HTTP 302, BLOCK; no direct bytes, redirects or active-list certification. Official search references suggest two-stage 2025 code transitions; do not infer an identity from suffix. Fixture collision initially failed #45829363781 (737 pass/1 fail); corrected e34bf3d400faea8b4d5c8978bfa47e8800fa26b4, #45829569351 738 pass + Ruff. Live probe manual-only, do not retry unchanged.
- Generic price adjustment guard 9114485b89e22cc449f8b213d951e64a49114e13: one action/factor at most once, fail closed on unresolved revisions or invalid arithmetic. #45829829666/job139943389462 759 pass, one intentional overflow warning, Ruff pass. Final provenance patch needs exact-SHA regression. No formal RESEARCH promotion, no accepted pin change, no private runner, no prospective settlement.

## 2026-11-26 — macro vintage and TWSE source maintenance
- ALFRED PAYEMS fixed four daily-vintage queries, #45832160262/job139951442006 at adaf36ddf92a26f2ee697a38e171b1e5020d9d20: all four TimeoutError, no bytes, BLOCK. No current-vintage fallback, no automatic rerun. #45832160289 768 pytest + Ruff PASS.
- TWSE official open dataset 18420 (Financial Supervisory Commission Securities and Futures Bureau/Taiwan Stock Exchange, Open Government Data License v1.0), October 2026 sample 2330. #45832552034/job139952804675 and #45832825328/job139953764854 obtained same 207911-byte CSV SHA256 0e6a2cbfb78befd2c77415e57aadfdf7acc1038a48e9d815bedb113730b622f2, parent rehash MATCH, first blocked rate schema; diagnostic actual rates 14.658949962741477/59.709757600700904/43.29045540365918. Issuer PDF and distinct issuer table HTTP403; no retry of these routes.
- Fixed observed fractional precision, #45833274854/job139955341474 at 5062a12123ee3d281239f7dd25998128bda073d1: exchange receipt OBSERVED, same raw hash, 1091 rows, snapshot Nov17 (not publication time), target October, amounts [586890319,511857399,367473051,4485617293,3130436902] TWD thousand, independently recomputed rates [14.658950,59.709758,43.290455] percent. Workflow success for exchange parser only; overall comparison INCOMPLETE/BLOCK, PIT false, rowset completeness false, no issuer retry, no causal A-share relationship. Raw CSV temporary only; no public raw retention. Observed precision regression synthetic CSV from logged fields is not retained original bytes. #45832552066 776, #45832825308 777, #45833274878 778 + Ruff PASS.
- Philadelphia Fed EMPLOY First/Second/Third M/M change workbook official source link https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/employ. Three real requests #45833405591/job139955801968, #45833627620/job139956588272, #45833834493/job139957313057 obtained identical 30749-byte SHA256 da5f3a884e5092c94bb53a8b5af828e111ccb25fdf8f39050769ca5ecd0dd406, rehash MATCH. Initial reader TypeError; bounded OOXML value reader replaced it, then actual multi-sheet scope failure; unique documented header selection attempted, final PHILLY_TARGET_SCOPE. Header found but unique sheet and exact August row not fully verified. No workbook values admitted, no source independence, no latest fallback, no historical capture, no raw workbook retention. Existing 3 retained BLS originals independently replayed each time. #45833405420 778 + Ruff PASS; #45833627538 780 tests PASS but I001 FAIL; fixed #45833834769 780 + Ruff PASS. Stop probes; all 3 new live workflows manual-only.
- Final exact-head public regression must be checked from Actions. Formal RESEARCH and private gates remain blocked; no accepted pin or frozen prospective receipt changes.

## 2026-11-26 — Turn 03 licensed source retention and actual industry execution
- TWSE dataset 18420 official license confirmed https://data.gov.tw/dataset/18420 and https://data.gov.tw/license. #45834919849/job139961118884 at e91dfaa41a54386b1eb42c92b253ad8a38aa038b: exact prior SHA256 0e6a2cbfb78befd2c77415e57aadfdf7acc1038a48e9d815bedb113730b622f2, 207911 bytes captured 14:02:28.910547 UTC. All 68 chunks reassembled, caller SHA256 and Git blob readback independently MATCH. Blob 1bf4790364b4ddf515d5fbd45af9b9c3bc437338 retained at eb6944be0330ca3637edfb4c60e590d73b377a93 with source attribution and receipt. First offline exact-byte test #45835294328/job139962440047 PASS at 14:04:45.2817217 UTC; conservative durable verified time 14:04:46 UTC. No historical capture before today, no vendor or issuer body publication. Path-scoped .gitattributes protects original CSV line endings. Retention workflow manual-only.
- Explicit INDUSTRY_MACRO profile TWSE_RETAINED_REVENUE_202610, exact subject TWSE:2330, source digest and both aware cutoffs required. Existing mainland default route unchanged; earlier-than-verified, date-only, wrong market/subject/digest and after sealed ceiling BLOCK. Actual #45835682825/job139963788397 at 98d6fd10829b49b72a004692135679229708ff9b sealed request pre-cutoff BLOCK, current observed archive WARN; parent artifact rehash MATCH. 1091 observed rows, 33 observed classifications, semiconductor 96/96 valid pairs; 1086 all-table YoY pairs (5 excluded: 1 negative, 4 zero base); 1084 rates match, 2 missing/unparseable, no conflict. Semiconductor 80/96 positive YoY, median 29.855329%, aggregate +60.779059%, ex-target +62.373682%; MoM aggregate +8.125533%, ex-target -0.214602%, median -1.967308%, positive 44/96; target 59.461802% of matched current revenue and 101.160133% of paired MoM change. All semiconductor rates match. All-table matched YoY +45.422193%. Actual archived-source visibility only, no independent upstream/complete market/first availability/historical PIT/causal A-share link or decision authority.
- #45836409431/job139966330823 at a4809239e2c4ce8ebb8535ccb78dafa0ac1553cc repeated **offline** replay for exact output packet export, not source fetch. Seven numbered chunks for 4 files: execution_request.json 1116 bytes SHA256 31a1a02bffbc0cb827b94e9446a435ceacbe227944368fa21cc9e41b83dca21c; execution_result.json 2081 a7c6591fb0293850c9e6a9e69d608afb3b0d99ad914dca57d998bf3730d88940; industry.json 9605 9f16c19823c8449651011e9a0197184362c787281c5a2e53f822050c82a0758b; run_manifest.json 833 a70eab480e6bfb86223bc75a5fc796f9d6ad259adeeffe353da0ca9a038d07e7. WARN and before-cutoff BLOCK again; caller-side packet verification and private storage documented in private records, not private runtime acceptance.
- Philadelphia Fed official notes page 1 https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/real-time-data/data-files/employ/specific_documentation_employ.pdf?hash=E4B6E855FAC21EE005FACC703B02B63C&la=en specifies yyyy:mm. Same exact prior workbook SHA256 da5f3a884e5092c94bb53a8b5af828e111ccb25fdf8f39050769ca5ecd0dd406, 30749 bytes. #45836042175/job139965048976 at 2d06ac187f0732e85a1d784ed8172a34f1880e94 target located but value schema BLOCK. Actual #45836409197/job139966330839 at a4809239e2c4ce8ebb8535ccb78dafa0ac1553cc two sheets, unique target 2025:08 in 749-row table, cells Decimal 22.0000 / str #N/A / str #N/A; first +22000 jobs matches BLS, both later explicitly missing; comparison INCOMPLETE/BLOCK. Official May 21 2026 methodology pp10–11 states intentional missingness near 2025 shutdown, no latest substitution. BLS originals alone establish +22000/-4000/-26000. No historical capture, exact intraday availability, or raw workbook retention. Stop all same-source retries.
- Public regressions #45834919733 780 + Ruff PASS; #45835294328 781 + Ruff PASS; #45835682836 793 pytest PASS but Ruff I001 (import ordering), fixed #45836042281 794 + Ruff PASS. #45836409236 794 PASS/1 FAIL due escaped regex on synthetic numeric string, fixed in final commit; actual Decimal/#N/A source result unaffected. Final exact-head regression must be verified. All new observation/replay workflows manual-only. Formal RESEARCH and private full gates remain BLOCK; no pin/frozen experiment change.
