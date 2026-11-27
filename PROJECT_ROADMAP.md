# PROJECT_ROADMAP.md｜InvestmentEvidenceEngine 路线图

更新时间：2026-09-02

## E0｜职责与合同
- [x] 无 AI / 无投资判断权
- [x] public-data-only
- [x] ExecutionRequest / ExecutionResult
- [x] artifact provenance
- [x] subject/executor 双 commit
- [x] PIT / failure / UNKNOWN 纪律
状态：`COMPLETE`

## E1｜公共证据 acquisition
- [x] 8 个一级 evidence domains
- [x] resilient market multi-upstream
- [x] provider cross-check
- [x] historical fundamental PIT guard
- [x] official-source fallback + token validation
- [x] SSE 多官方路径韧性
- [x] CSRC 多官方路径韧性
状态：`COMPLETE_FOR_V1_CONTRACT`

## E2｜研究计算资源
- [x] PIT_REPLAY
- [x] FACTOR_COMPUTE
- [x] BACKTEST
- [x] OPPORTUNITY_SCAN
- [x] PORTFOLIO_MATH
- [x] TEST_SUITE
- [x] scanner 仅 research-priority semantics
- [x] portfolio math 仅 generic/synthetic
状态：`IMPLEMENTED_UNIT_TESTED`

## E3｜独立 Public 仓
- [x] 创建 Public `riyuewuxing/InvestmentEvidenceEngine`
- [x] bootstrap 迁到 repo root
- [x] canonical implementation 切到独立仓
- [x] regression workflow
- [x] provider-health workflow
- [x] execute-request workflow
- [x] `repository_dispatch: execute-evidence-request`
- [x] sealed/public-only firewall
- [x] canonical accepted executor commit 固定为 `86887ff40fee3166629f6e14d7531fe9542cc266`
- [ ] Git tag / GitHub Release（当前连接器无创建 tag/release 写动作；commit SHA 已作为可复现 pin）
状态：`COMPLETE_EXCEPT_OPTIONAL_TAG_SURFACE`

## E4A｜Pre-Public GitHub-hosted runtime
- [x] regression 13 tests + Ruff
- [x] real `600519` acquisition/compute/render
- [x] artifact byte re-hash
- [x] EvidenceAdmission / EvidenceGraph
- [x] CommanderEvidenceSession / DecisionMemo graph binding
状态：`PASS_PREPUBLIC`

## E4B｜Public runner 真验收
- [x] install / pytest / ruff — run `33536018264`
- [x] provider acquisition / cross-check
- [x] official source 3/3 — run `33536018282`
- [x] Kline artifacts
- [x] artifact upload/download
- [x] private consumer admission
- [x] subject/executor 双 provenance
- [x] executor commit pin
状态：`PASS_WITH_EXPLICIT_WARNINGS`

## E5｜Public Vertical Slice
- [x] sealed real-company request
- [x] Public executor repo/commit
- [x] Public Actions artifact — run `33536165615`
- [x] observed artifact SHA verification — 9/9 match
- [x] private EvidenceAdmission
- [x] private EvidenceGraph
- [x] Commander structural binding without investment conclusion
状态：`COMPLETE`

## E6｜规模化与治理
- [ ] representative factor/backtest Public runtime benchmark
- [ ] full-market scanner performance benchmark
- [ ] matrix/sharding
- [ ] rate-limit/backoff/degradation policy expansion
- [ ] data-license/redistribution review
- [ ] source schema drift monitoring
- [x] scheduled provider health foundation
- [ ] release compatibility matrix
- [ ] artifact retention / size policy hardening
- [ ] security / secret scan
- [ ] SBOM/dependency policy
状态：`NEXT_MAJOR_WORKSTREAM`

## E6 supporting infrastructure — visual QA
- [x] Synthetic public browser/native capture implementation and bounded log return
- [x] Actual public runner + independently decoded and viewed all three PNGs (run `45369573507`)
- [ ] Product-specific test integration only after public-safe source authorization or private/local execution
Status: `SYNTHETIC_CAPTURE_TRANSPORT_VALIDATED` at `853f39a94d69ce7fbb4b88a1e7714d97ca7ce76d`; follow-up lint/receiver tests separately verified. Private product not validated.


## E1 corrective maintenance — valuation history
- [x] Implement strict date-bounded valuation observation; no automatic PIT/decision promotion.
- [x] Add synthetic cutoff/schema/identity/duplicate regression cases.
- [ ] Verify same-SHA public regression and separately bounded real-provider schema.
- [ ] Private consumer compatibility and exact-version admission; do not auto-advance accepted executor pin.

## 2026-11-26 targeted evidence maintenance
- [x] Real public date-bounded market observation (run 45809117132; WARN, single source, no vintage proof).
- [x] Bounded independent listing diagnostic (run 45808245082 BLOCK; do not treat a timeout as verification).
- [x] Public scan attachment byte/selector binding and fail-closed RESEARCH boundary implemented; final exact SHA regression must be read from Actions.
- [ ] Obtain actual admissible public candidate bytes and original-source receipts with publication/retrieval provenance; independent listing/price checks remain open.
- [ ] Implement and validate genuine PIT research profile with chronological splits/cost stress; do not invent available_at from bar dates.
- [ ] Private consumer complete same-SHA dual gates under public-only boundary. Historical pins remain frozen.

## 2026-11-26 continuation — observed research diagnostics
- [x] Actual two-route unadjusted OHLC control and fixed retrospective cost stress (459 bars; no historical PIT proof).
- [x] Production raw secondary crosscheck (38 bars, WARN).
- [x] Official SSE main/STAR listing observed and raw rehash (1700 + 619, scope only); exact packet replay synthetic tests.
- [ ] SZSE official transport and full independent listing coverage, actual public candidate packet; no forced full scan while gate BLOCK.
- [ ] Genuine historical availability, corporate actions/cost/execution proof, real research profile and formal private same-SHA admission.

## 2026-11-26 — exact real candidate diagnostics
- [x] Public disclosure-directory / scan packet exact replay (WARN, limited scope).
- [x] Same-run first real candidate retrospective raw-price diagnostic (WARN, ex-post; not formal RESEARCH).
- [x] Shared strict candidate selection schema and fail-closed crosscheck receipt checks; verify final regression.
- [ ] Official SZSE active-list coverage, independent price and vintage provenance, retention permission and independently verified original attachments.
- [ ] Real historical PIT fundamental/research profile and private same-SHA formal admission; no freeze settlement before due time.


## 2026-11-26 — issuer revision and source chronology
- [x] Actual dated original issuer PDF observations and exact cross-host matching, consolidated cashflow and Q1 opening adjustment reconciliation (WARN).
- [x] Actual CNINFO metadata ID/attachment/timestamp check, PIT replay sealed-cutoff / dependency guard.
- [ ] Latest Q3 actual report, complete revision universe, captured historical vintages, durable permitted source bytes and formal PIT RESEARCH.
- [ ] Official full SZSE active listing / private dual gates; keep frozen prospective control until its existing due time.

## 2026-11-26 continuation — actual Q3 and permitted retention
- [x] Exact Q3 alias, two official originals and original/restated comparative values; consolidated balance/flow reconciliation.
- [x] Three fixed public-domain BLS originals content-addressed; independent byte rehash, offline actual-byte regression (verify exact final SHA).
- [ ] SEC network 403, official SZSE coverage, historical first availability, independent vintage data and formal RESEARCH/private dual gates. Do not equate current archive observation with historical availability.

## 2026-11-26 — Turn 06 continuation
- [x] Actual official SZSE aggregate (different scope, not full A-share list), alternate first-page HTTPS attempted and blocked.
- [x] Actual 000035/510300 two-source-per-asset date sensitivity, retrospective only.
- [x] Existing factor/backtest integrity and exact-byte public/consumer guards; explicit revision-chain offline real-original replay.
- [ ] Full official listing, genuinely time-visible historical evidence, formal RESEARCH profile and private same-SHA gates. Do not repeat completed probes.

## 2026-11-26 cash / identity maintenance
- [x] Real two-source cash-entitlement sensitivity, WARN only.
- [x] Factor cutoff and adjustment ambiguity guards; verify final same-SHA regression.
- [x] BSE official routes attempted, BLOCK 302; no active list obtained.
- [ ] Actual historical first availability, verified complete corporate actions and listing, formal RESEARCH and private dual gates.

## 2026-11-26 macro-vintage / TWSE increment
- [x] ALFRED four fixed vintages attempted, timeout BLOCK (no fallback).
- [x] Actual TWSE exchange numeric receipt, precision correction and independent amount/rate checks, scope limited to one target row. Issuer cross-check BLOCK in runner, no PIT proof.
- [x] Philadelphia Fed workbook actual bytes observed, exact August row BLOCK; manual-only, do not retry unchanged.
- [ ] Genuine source vintage and historical first availability, full official listing/corporate actions, real RESEARCH profile, private same-SHA gates.

## 2026-11-26 Turn 03 licensed originals / actual sealed industry research
- [x] One exact open-licensed TWSE original retained and independently reopened; attribution and byte-level receipt.
- [x] Actual sealed INDUSTRY_MACRO profile, sector breadth/amount pairs, ex-target concentration and explicit observed-time guard; WARN only, earlier cutoff BLOCK.
- [x] Actual Philadelphia first value matched, later source cells explicitly #N/A; methodological missingness, no latest fallback, complete comparison BLOCK.
- [x] Export exact bounded public sealed research packet; record independently verified packet in private master record, no private runner.
- [ ] Genuine A-share historical time-effective source coverage, full listing/corporate actions, formal RESEARCH profile and complete private same-SHA gates. No repeats of finished controls.

## 2026-11-26 Turn 04
- [x] Actual IPO, delist gap, A/B identity and merger termination notices, date-scope WARN.
- [x] Actual two issuer PDFs, aggregate consideration and dual-route exact endpoint marks; intermediate value unknown, fractional allocation not inferred.
- [ ] Official complete historical listing and corporate-action coverage, first availability, formal RESEARCH and private full same-SHA gates. Do not repeat completed fixed controls.

## 2026-11-26 Turn 05
- [x] Existing price and chart consumer subject/time/basis/row integrity; bounded standalone fetch and complete observed-row metric windows.
- [x] Real sealed 600519 market-to-price-to-chart control, same bars and exact cutoff; WARN only, no true historical vintage.
- [x] Existing formal RESEARCH BLOCK exposes transport vs unadmitted prerequisites, without granting access.
- [ ] Genuine historical point-in-time evidence, full listing/corporate-action coverage, actual execution/cost inputs, formal profile and full private same-SHA gates. Do not repeat finished controls.

## 2026-11-27 JST Turn 06
- [x] Actual new SSE delisting directory response, exact-version duplicate exclusion and retrospective date-interval coverage.
- [x] Existing factor/backtest dependency cardinality and market identity binding; public 845-test regression.
- [ ] SZSE delisting/active listing, resolve SSE duplicate keys/identity semantics, full point-in-time universe/company actions, formal RESEARCH profile and private dual gates. No blind retry or guessed deduplication.

## Turn 02 — bounded research profile
- [x] Execute actual production RESEARCH arithmetic from real scanned candidate + same-window raw-market attachment; retain formal BLOCK.
- [x] Exact serialized input/window binding; separate full/validated/computation fingerprints and exact recomputation; explicit prior-version mismatch.
- [x] Public arithmetic and regression controls (895 + Ruff); both new live controls manual-only.
- [ ] Genuine historical source/version/availability evidence, complete listing/actions, independent source/actual execution/cost evidence, formal profile and private full gates. No unchanged diagnostic rerun.


## 2026-11-27 JST — Turn 03: issuer cash entitlement, ex-reference and execution status
- Code/test checkpoint 3d2dfd623b43751a48ddda2b0a592d55a35966d1; regression #45858649536 / job 140043557263: 940 passed, 2 warnings; Ruff passed. Earlier #45857757650: 937 pytest passed, import lint failed, corrected in #45857980155. No final-code live replay claimed.
- Actual #45856529066: three issuer PDFs (2025 dividend, treasury cancellation, registration) 439046/125422/65085 bytes, parent/temp SHA match. 000035 gross cash .0352 vs ex-reference deduction .0336129; cancellation of 112750413 treasury shares does not imply holder-unit change. 2026 cash .036, all shares eligible. #45856977986: prior 2026 PDF SHA matched, newly checked fields; 459 sessions, 693 calendar days, two events reconciled, legacy assumption BLOCK (4.31 vs observed 4.32), explicit terms MATCH (4.32); 2026 reference 4.54. Current backfill, not PIT, original bytes not retained.
- #45857757670: 459 observed BaoStock rows tradestatus=1/isST=0, Tencent exact OHLC agreement, ordinary SZ main-board conditional opening obstruction 40/8/6 intended transitions, zero adverse open-limit flags; no actual execution or cost proof. No historical identity or exceptional regime proof. First prior session not independently checked.
- #45858212347: original 2023 official URL 404, 2026 PDF 282084 bytes matched hashes and clauses. #45858449343: different official archive URL for 2023 PDF 620843 bytes matched hashes and clauses. No unchanged repeat or claim of historical availability.
- Shared cash entitlement/action reference supports explicit terms, exact Decimal arithmetic, bound disclosure/record/ex dates, no legacy receipt rewrite. Conditional execution check rejects hidden calendar gaps and malformed status. Old 600519 action workflow accidentally auto-triggered #45856612757 (243 sessions, legacy assumptions); disabled push trigger. All new observation workflows manual-only. No private inputs or runners; no accepted pin or frozen experiment changes. Formal RESEARCH remains BLOCK, private full gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION.


## 2026-11-27 JST — Turn 04: issuer accounting and nominal entitlement/tax sensitivity
- Code/test checkpoint `6e378fbe8eff2c8ebf7fb4a866108b20a350bc0d`; exact regression #45862061678/job140055330385: 977 passed, 2 warnings, Ruff PASS. Earlier #45860538531 and #45860749025 pytest passed (946 and 958) but import lint failed; corrected #45861049173 960/Ruff PASS. Subsequent exact 967, 974, 975, 977/Ruff checkpoints passed. No claim that final-code SHA re-observed network sources.
- Actual issuer control #45860538511/job140050086834 @90848a3: all five PDFs parent/temp rehash MATCH; 2025 approval fields BLOCK due attendance on p2, four other documents OBSERVED. #45861049803/job140051859346 @13a1198: reobserve ONLY 2025 approval exact SHA 7c772e04612bf868b331f495758bbd75e01df4531cfaa2a0f9d6a22934227caa, p1/p2/p4, reuse four pinned prior derived receipts. WARN; 2025 approval votes 907417360/3100738/480600 (99.6069%); 2026 801288620/2757500/134000 (99.6404%). 2025 implementation 84058753.47 vs H1 84058749.04 and annual 84058749.07, deltas 4.43 and 4.40; annual-H1 .03. 2026 implementation/H1 accounting 85969179.68; H1 period-end ordinary payable same amount, previous cell blank not zero. 2025 H1 payable label 108340447.03/12936647.52 aggregate, not event-specific. Discrepancy cause and actual paid/holder credited cash unverified; accounting period end not payment date.
- Actual #45860749145/job140050813661 @b18eca6: one new Tencent direct original body 69797 bytes parent rehash MATCH, 459 rows, date/open/close projection exact 4cfa27ad4f03e5877d5a06e14e90a814240bb41c532ec5631a7c4d33c593e4e3, temporary projection rehash and prior fixed price profile canonical hash b6424c54dc79fa3575f74c8657a3a8a9decf8c7ae2aa9ed81dd1e15dd27170ae both MATCH. No full-market version identity claim. Added nominal gross cash sleeve using prior record-close holding (buy ex-open excluded, sell ex-open including terminal retained), no reinvestment/available-cash assertion, independent split resets, price-only signal and fee assumptions unchanged. 10bp signal train 16.2206619460% -> 16.8811009481%, validation -17.1856188986% unchanged, test -11.6140913836% -> -10.8933699407%; conditional sensitivity only, not a total-return backtest, decision, or strategy forecast.
- Actual #45861693923/job140054074387 @83405d3: official tax rule and explanation HTML bodies 26556 and 32341 bytes, both parent rehash MATCH. 2015 rule reviewed effective tiers 0/10/20%, withholding on transfer for holding <=1 year, FIFO/natural-calendar holding and transfer settlement date boundary. 27 strategy/split/cost rows from retained derived receipt sha256 abe7050f6592433f207b750e88810a9f09add2dd682f3abede5c23fa1c1a90b7; no new market fetch. 10bp test signal nominal 0/10/20% tax scenarios -10.8933699407/-10.9654420850/-11.0375142293%; no actual holding-period classification, account tax or paid cash. Original provider/PDF/HTML bodies not retained.
- Shared pure modules momentum_entitlement, dividend_tax_sensitivity and research_profile_evidence bind exact caller term bytes to validated raw-market artifact, preserve original baseline and conditional-only output. Explicit offline fixture integrity and split boundary regression. All three new live workflows manual-only; bounded job/steps/child watchdogs. Formal RESEARCH BLOCK, no accepted-pin advance, historical availability, complete corporate actions, historic universe, independent provenance or actual cost/fill proof. Private full gates remain NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION.


## 2026-11-27 JST — Turn 05 historical SZSE roster diagnostics (T0 13:15:46)
- Exact regression checkpoint 78a303687291a89cfa27604a80a5c94dadeddea3: run 45940388788/job 140313102963, 988 passed, 2 warnings, Ruff PASS. Only public computation. Both factbook workflows now manual-only. Public source observation is not private authority acceptance.
- Actual #45939074990/job140308943336 and #45939309237/job140309699966: 2024 SZSE yearbook 17,220,384 bytes, 1,719 pages, SHA256 ce2d0fd45f90284d8cf6a0663c68c61c76dd0250a73ff94da5982a981195cd2e. Edition October 2025. ChiNext 1,365 unique rows, matching two code sets, valid rank order, aggregate -0.10 million CNY vs printed total. Main all 1,543 rows BLOCK, 1,524 unique, 19 duplicate codes, 3 extra, inversion at 1521/1522. Poppler comparison not obtained. Exact rank projection repeat MATCH, not independent publisher vintage.
- Actual #45939705961/job140310944776: five original PDFs transiently verified with parent/parser SHA MATCH. First 1521 main ranks unique in both columns, equal sets, descending, 1482 A / 39 B using issuer-specific 201872 B identity, matching actual Jan 2025 monthly domestic counts. Main value delta +0.01 million CNY, within rounding; first partition set SHA 485a191bc4089b6e77f0a8b9ac305ded00792036de78fb23b2f2995374e8509c. Tail 22 rows = 19 repeated + 3 extra (002740,002776,200413). Issuer notices for latter two observed. Actual #45939986675/job140311841819: 002740 decision dated 2024-02-08 on exchange plus issuer notice from media PDF, scheduled delisting 2024-03-04, both hashes MATCH. All three tail-only identities now have issuer-reported exit evidence; diagnostic partition only, not official correction or complete historical membership admission.
- Actual monthly security counts SZ A 2847=1482+1365, B39; SH A2274=1693+581, B43; BSE A262; national A5383/B82. No other exchange roster inferred. Monthly SZ company count2851 vs official year-end overview web text2852, main1486 vs1487; overview runner #45940266895/job140312736690 BLOCK (worker failure), no original bytes or explanation. No unchanged retry. Original copyrighted tables and bodies not retained.
- CAPCO H1/H2 downloads both BLOCK, no extracted association roster. Issuer reference H1 003020 report 2024-10-30 cites 2024-09-30 release; H2 002616 report 2025-08-30 cites 2025-04-18 release. H2 field mismatch corrected by targeted page reparse #45939510952/job140310335151 exact SHA. Real dates regression rejects backdating to half-year, release or report day. Date precision and current retrieval do not establish first availability. Existing effective-only interval consumers cannot be considered PIT admission without observed knowledge lineage; no private runtime changes.
- BLOCK remains: genuine historical availability, complete listing universe, source-independent exact histories, full corporate actions and execution evidence. Private gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION. Frozen prospective experiment no settlement before 2026-11-27 15:30 CST. Next: no repeated yearbook or blocked unchanged downloads; prioritize new sources for historical roster coverage/verified availability, formal research prerequisites; prospective settlement only after authorized cutoff.

## 2026-11-27 13:38 JST — new session Turn 01, historical roster diagnostic
- SSE #45942021737: 832pp/37592482B same original, 2334 unique fully parsed trading rows; 2278 unique companies. Excluding 16 A and 1 B trading-only yields 2317 securities, ordinary A2273/CDR1/B43; exact company A set match; cap residual +0.05 million CNY. Initial directory date parser BLOCK; exact same directory #45942214665 verified 17/17 identities/dates via strict date parser. Independent original aggregate #45942442580 2pp/89073B confirmed A/CDR/B/company/market cap and board counts. Prior national A-style 5383 includes CDR; ordinary A aggregate 5382, B82, not national exact set proof.
- CSRC #45941537897 CQ78 (SZ37/SH35/BJ6); #45942047634 Shanghai447 Shenzhen422 exact landing page and attachment hashes. Jiangxi #45942245524 total85 = disjoint SH33+SZ52, one unidentified nonempty 10-row sheet keeps workbook BLOCK. #45942580454 watchdog 60.003 sec, no bytes; misleading prior_version_mismatch corrected to NOT_OBSERVED vs MISMATCH without repeated network request.
- BSE #45941889323 CAPCO mapping blocked; same IPO PDF #45942290224 parsed 24 rows (23 in 2024, 9 legacy/14 native). Alternate CNINFO regulatory attachment #45942357137 real raw bytes/parent/parser SHA MATCH: 248 one-to-one mappings, nine 2024 legacy code-date matches, 14 disjoint native 920 -> 262 candidate, SHA 4b5218b27e2d1737d51e7f77671fff0dce6e0bf9d36fae5895616792d3c3d0b2. 26 suffix exceptions, 68 selected-layer pre-BSE dates. 2024-12-13 archive path, separate notice #45942507943/#45942629809 original SHA MATCH, date/notice number/attachment title/transition clauses true, title extraction false both modes => BLOCK; screenshot visible title not promotion. No historical first-availability proof or code cutover backdating.
- Public exact implementation/guarded manual workflow SHA 4eaf303d52920c4c5fb8e38891cf0ab3cc9d16e3, regression #45942763119/job140320547648 actual 1002 passed, 2 warnings, Ruff passed. Four temporary push triggers closed; public-only guards. No formal research admission, no private runner, no trading. Private dual gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION. Frozen prospective no settlement before 16:30 JST (15:30 CST). 
- Next: do not repeat completed yearbook or unchanged blocked source attempts. Prioritize verified historical publication vintages / eligibility and original corporate-action evidence; prospective settlement only after frozen cutoff; no accepted pin advancement.

## 2026-11-27 14:01 JST — new session Turn 02, cross-exchange disclosure clocks and action reference
- HKEX/SZSE/CNINFO BYD 2024 interim exact identities and six financial comparative cells reconciled. #45943490059 initial HK parser BLOCK, #45943627633 same-byte CJK BLOCK, #45943718461 same-byte English anchor WARN; #45944132723 CNINFO WARN exact ID1221030553, same SZSE original SHA efa9b512e85b259c85c481c6d6a49e450a2f9e739886fd5255da136841986216 despite Aug28/Aug29 path dates. HK publisher 2024-08-28 17:55 HK minute (not instant); CNINFO platform midnight 2024-08-29 CST (not first availability). Observations 2026 only. Same issuer, not independent audit. No historic byte retention.
- Production public PIT_REPLAY dependency completeness, explicit record collection, clock alias and admission/verification chronology guards. 631d9368a3ddfadb2de5e54a1fc20cc244d45d06 sealed real-derived fixture: four historic cutoffs BLOCK, one before complete modern observation BLOCK, after all modern observations WARN, no PIT/admission authority. #45944132733 target-scope regression repaired and retested #45944314074. CDX actual #45944374266 two HTTP200 empty results for exact 2024 H/CNINFO PDF URLs; archive witness BLOCK, absence not proven. No identical repeat.
- Actual #45944680758 cancellation and distribution original bytes, parent SHA MATCH. Cancellation 2024-05-10 1,877,000 shares, no investor unit factor or entitlement inferred. 2025-047 A-share distribution record Jul28/ex Jul29: 3x old holder units, gross CNY3.974 per old share, bonus face value tax base distinct. #45944850802 observed BaoStock/Tencent 24 same date labels, close within 0.011 CNY. Jul28 337, Jul29 111.42, conditional reference 111.01 = vendor previous reference, ex-date factor present. Raw price -66.937685%, conditional gross wealth +0.366172%. Not actual credit/fill/tax/official reference or complete action history. No vendor raw retention.
- Final exact code + guarded manual workflows SHA 9cfbe3da08cd86478d9bc03b4bb01f1613bebff0, regression #45944969767/job140327459148 actual 1034 passed, 2 warnings, Ruff passed. Earlier #45944850877/#45944924652 pytest passed/Ruff import failed, exact fix verified. Four temporary push triggers closed. Private static audit only; no private code or runner changes, accepted pin/frozen receipt unchanged. Formal RESEARCH BLOCK, private dual gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION. No settlement before 16:30 JST (15:30 CST).
- User-approved focused closeout estimate 8–12 turns from this phase; this turn is first after agreement, not a completion guarantee. Next Turn 03: corporate actions/adjustment/trade eligibility, build on completed BYD evidence rather than repeat it. Check action completeness, no adjusted-price/cash double count, execution feasibility, and eventually full formal gates. Historical first availability remains external evidence gap; don't spend repeated turns on unchanged blocked source paths.

## 2026-11-27 14:27 JST — new session Turn 03, corporate actions and historical trade eligibility
- Public retrospective 2025 世龙实业 sz.002748: initial #45946203142 BLOCK on suspended-day missing volume; #45946329794 corrected WARN, issuer PDF same bytes parent MATCH (SHA 3e81336b3b2a9826aa3a34a8065582bad8b2c118ded51364159d43225caa9f99), 15 scheduled/14 traded days with exact BaoStock/Tencent OHLC; May20 ST5, May21 suspended (blank volume not zero), May22 ordinary10. No fill or historical vintage proof.
- Public retrospective 2026 ST海王 sz.000078 rule-date transition #45946785657 WARN: 8 traded days exact two-source OHLC, ST flag unchanged, Jul3 close 1.49 at 5% upper, Jul6 close 1.64 at 10% upper. Issuer notice SHA 79a18beafde41d075a7385b3c1126abd178805af7a041d4188c0b6dbfb75291d parent MATCH; SZSE effective date Jul6 reviewed. Date-aware ST5/ST10 vs ordinary10, exact session coverage, no missing-volume imputation or first trading day event reference injection. Exceptions not exhaustively verified.
- Shared holding_risk/HistoricalReceipt V3 explicit post/pre share ratio and gross cash per old unit, RAW_CLOSE only, mutually exclusive legacy cash list, duplicates and wrong subject rejected, record/ex-session relation, canonical V1/V2 byte compatibility. Real BYD/510300 V3 control #45947071048 WARN, 77 sessions 2025 Jun16–Sep30, 3+2 providers MATCH, temporary receipt baf0361b9d731fdcc182d9908e05e883bf8ab9a0bc52b39522054b52241ce071 rehash MATCH; BYD raw -68.2925413%, specified-event conditional -3.74671885%, ex-day +0.3661721068%; ETF other events not accounted for. Actual receipt-derived issuer terms reused, no repeat PDF request. Not actual credit, tax, cost, total return, complete action coverage or PIT. 1/5 session descriptive, 20 session insufficient.
- Public final code/guarded workflows b5639d8fddbf73f6cff827c52899006dcb59d932, exact #45947222476/job140334581128 1061 passed, 2 warnings, Ruff passed. Earlier import errors fixed. Three incidental pre-existing push-triggered live controls ran successfully (#45946055394, #45946486264, #45946486403), not intentional new probes. Six related live controls now manual-only; no private runner or private-to-public data/code upload.
- Formal RESEARCH BLOCK; private dual gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION. Accepted pin and frozen prospective unchanged; no settlement before 16:30 JST / 15:30 CST. Public eligibility is diagnostic, not actual trade execution. No change to frozen momentum profile. Next Turn 04: advance execution feasibility/friction and explicit source-dependent gate audit (including private cash backtest's assumed previous-close reference, limit rounding, unmodeled corporate action cash flows/share quantities, and no actual fill claim). Do not repeat completed ST and BYD controls or unchanged blocked archive routes. Keep private runtime verification separate, no pin promotion.

## 2026-11-27 14:56 JST — session Turn 04 (redo; prior aborted turn void)
- Shared cash_execution_math exact Decimal cent/tick bounds, commission/transfer/stamp per-order, bounded affordable-lot search, strict reference_chain with missing/non-cent reference, one-cent discontinuity, suspension/volume conflicts and unanchored first predecessor. No complete historical vintage, corporate-action, calendar or fill proof. Public tests cover previous actual ST/BYD boundary cells with explicitly synthetic ancillary inputs.
- Actual new 000001 July 1--Aug 31 2026 strict chain #45949979434/job140343331077: 44 expected/observed sessions, BaoStock raw and Tencent OHLC exact MATCH, no breaks, conditional continuity WARN, first predecessor unanchored, no vintage or complete action proof. Tencent body parent rehash MATCH. No repeat of old ST/BYD probes.
- Actual #45949389371/job140341454769: 000001 bid/ask 12.26/12.27 same prices but provider clocks 3s apart, strict depth BLOCK; 510300 exact same-second five-level match, 100 units assumed buy 413.60+5=418.60, isolated sell 413.50-5=408.50; static display only, no actual broker rates/fill, inventory, queue, impact or future execution. Overall BLOCK by design. Raw hashes and normalized receipt rehashes observed, no raw upload/retention. No retries to manufacture a PASS.
- Public final executable/workflow SHA 8c345ffab4c9c9ff4f6d381bab691de6d2476765, exact #45950131560/job140343807346: 1103 passed, 2 warnings, Ruff passed. Earlier #45948845441 four fixture failures (required order count) fixed, subsequent exact public regressions passed. Quote and new historical diagnostic workflows manual-only, bounded workers/timeouts; no private compute.
- Formal RESEARCH remains BLOCK; historical source vintage, full action/identity coverage, actual fee/fill provenance, complete historical universe and independent source constraints remain. Private full gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION; do not promote accepted pin or frozen profile. No prospective settlement before 2026-11-27 16:30 JST / 15:30 CST; verify actual time first. Do not reopen unchanged blocked routes or repeat these diagnostics.
- Next Turn 05: focus real research workflow/reproducible study, explicit dependencies, source provenance and falsification gates, rather than new infrastructure. Preserve sealed precommit and forward-only frozen observation; if after cutoff, use existing settlement protocol exactly. Distinguish conditional study output from admitted evidence and decision authority. No Round4 authorization.

## 2026-11-27 — new session Turn 01 / previous Turn 05: actual research falsification and dependency proof
- Public code/workflow final tested `0785546ef571ca146f7a9f3e4410b7d67d97d73c`, exact run #45953411187/job 140354253105: 1180 passed, 2 warnings, Ruff passed. First regression #45952224087 had one existing universe fixture mismatch after all artifact refs became explicit; corrected. Factor/BACKTEST consume exactly one observed, explicitly identified table from one completed dependency, byte/size/hash/context binding; no silent fallback, summary-table extraction or multiple source splicing. Bound daily-market midnight serialization is normalized only to a date label, never an availability instant; inline and intraday guards remain strict.
- Real predeclared convenience controls 600036 and 600900, 2025-01-02--2026-11-25, retrospective as_of 2026-11-26, no tuning, no representative or historically preregistered claim. First actual run #45952345771 both got 459 dual-route matching rows but blocked on time-label format; scoped correction #45952626339 verified sealed factor artifacts and formula. New independent Decimal lagged allocation/fee/return/drawdown oracle, #45953263062/jobs 140353786742 and 140353787023: 459 rows each, 439 valid factors, 20 warmup nulls, 27 matched metric cells per subject, 87 test intervals, same signal projection hash and same conditional comparison results as prior effective observation. Retrospective unadjusted price diagnostic only, not total return/PIT/execution. Both failed predeclared strict joint dominance over same-period constant invested and zero-interest cash at all 10/20/30 bp tiers. At 10 bp signal/hold 4.23/15.24% and 6.61/14.51%. No rule or sample replacement. Actual source bodies not retained; derived receipts and hash witnesses only.
- Real same-day intraday scan #45952854969/job140352474677: 5580 raw/5579 normalized, top20 independent ranking and exact producer replay/attachment rehash MATCH. Single Sina route, quote day unknown, listing unavailable; no closing quote or full membership claim. Additional independently bound source quality metadata tested in public regression; old actual producer byte replay already checked its complete output. No repeat acquisition for metadata-only patch. Shared scan_selection includes rank, row, count, rule, stable tie and metadata proof. Both live controls manual-only, bounded timeouts, no automatic rerun.
- Formal RESEARCH remains BLOCK: historical vintage, complete historical listing/identity/corporate actions, independently available-at evidence and real brokerage fees/fills remain unadmitted. Private full dual gate NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION; no accepted pin or frozen experiment changes, no Round4. Private integration and derived receipt archive recorded privately, no private data here.
- Next Turn 02: continue focused 4.0 closeout. Do not repeat unchanged 600036/600900 or universe acquisition; prioritize actual historical source/provenance/admission gaps, precise unsupported-vs-missing evidence and formal research entry. If actual time >= 2026-11-27 16:30 JST / 15:30 CST, execute existing frozen prospective settlement protocol exactly; otherwise leave frozen result untouched. Multi-day starts 11/30. No new unsupported formal promotion.

## 2026-11-27 15:52 JST — session Turn 02, historical observation and vendor scope
- Public final executable/workflow checkpoint `ce3d13890578de587d2f280753bfd7d640ffe954`, exact regression #45956244559/job140363265148: 1259 passed, 2 warnings, Ruff passed. Baseline 1180; +79 tests. Initial PIT dependency #45954929469: 1199 passed. Common Crawl and vendor scope regressions 1211/1245/1256; offline dependency 1257. Two sealed-control regression runs #45955858670/#45955930768 had pytest pass but Ruff import formatting failure; fixed #45956060720, final checkpoint retested.
- Production PIT_REPLAY binds every declared dependency to one exact artifact path, size, SHA256 and canonical typed JSON, records per-source row index, rejects absent/mismatched/ambiguous upstream records and conflicting additional observation/ingestion/effective clocks. Eligible indices computed in one pass. Clock chronology is not historical source-vintage admission.
- New Common Crawl exact URL index/WARC route: bounded fixed HKEX 2024 interim PDF in CC-MAIN-2024-38 and -42 returned HTTP404; CNINFO exact PDF in -38 returned HTTP503 and stopped, no retry. #45955024845/job140359390799: 0 witnesses, BLOCK, no absence assertion or original bodies retained. Existing Wayback empty/SEC 403 not repeated.
- Three prior public-domain BLS original PDFs reopened and parsed without network. Actual #45955376653 dependency boundary control gives BLOCK/BLOCK/WARN/BLOCK/BLOCK/WARN and rejects mutated dependency. However its source_rows log was mutated by the tamper control through an alias; first sealed run #45955858688 inherited that wrong value. Both are superseded for numerical source values, retained as failure evidence. Fixed isolated dict + explicit exact source value assertion. Corrected sealed #45955930825/job140362279844 @d635ca8e89971303799706e58af17b6ca117a118 verifies original 22000,-4000,-26000 (2025 Aug payroll change releases). Historical full chain BLOCK; first actual durable cutoff BLOCK, after all durable checks WARN. Request/result/artifact/manifest hashes MATCH; upstream BLOCK prevents downstream execution; merged three values and indices exact. Inline local source projections, not proof of remote official producer provenance or historic first availability. No network or new original body retention.
- Shared vendor_financial_scope rejects malformed/conflicting announcement clocks, nonconsolidated or adjusted report types, different issuers, conflicting same-day revisions (no update_flag fallback). Optional public Tushare fundamental path requires exact one stock/issuer, sealed date ceiling, no historical live-snapshot substitution, explicit report_type 1; 25s/4MiB bounded worker per endpoint, parent revalidates identity and clock, no token argv/log or retry; no actual Tushare credential/live observation in this turn (synthetic tests only). No historical-vintage promotion. Common Crawl and both retained-PIT workflows now manual-only.
- Formal RESEARCH remains BLOCK: historical source vintage/first availability, complete listing identity/action coverage, independent historical provenance, actual fees/fills still not admitted. Private dual gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION; no accepted-pin advancement, no frozen experiment change or Round4.
- Next session Turn 03: continue focused 4.0 closeout, do not re-fetch unchanged Common Crawl/Wayback/SEC targets or repeat the retained BLS proof or 600036/600900. Before any prospective settlement, check real JST time; only if >=2026-11-27 16:30 JST / 15:30 CST execute existing frozen protocol exactly. Multi-day starts 11/30. Prefer practical research/decision workflow remaining gaps and explicit formal evidence prerequisites; no fabricated PASS or unsupported promotion.

## 2026-11-27 — session Turn 03: ETF original-report reconciliation and first mature prospective outcome

- Start 2026-11-27 16:17:33 JST. Public-only computation; per-task watchdogs (PDF 30s each; historical normalized source 25s each; outcome step 120s / workflow 8min). No private runner, no Round4, no accepted executor pin change.
- Public fixed convenience report pair 510330/510320, 2026-Q3: two genuine official manager/exchange PDFs, hashes f0b3d948633558c55317fbc852257eb9657dfef3c47e89d5a9e5fe80ab099826 / bce1bb11a2e0898b37f174ebbb96bba30794167a0cffc4e8b3182365dd86241c. First live #45957994379 blocked on compacted financial-row ordinals; corrected #45958260768 blocked on share-row typography; exact same original bytes #45958440503 / job 140370277263 fully reconciled NAV, shares, accounting and reported common-period returns. No source body retained. 3M returns -11.62%/-11.55%; 6M -0.45%/-0.66%; 1Y -3.98%/-4.24%; net creation units +1,017,900,000/-6,000,000; not CNY flow, not tracking error, not actual holder net return, not future alpha. Report first availability and benchmark version remain unverified.
- #45958611216 / job 140370841997: both Sina and Tencent normalized unadjusted closes for both ETFs across 22 common dates, full-window crosscheck MATCH within tolerance, exact terminal close 4.621 / 1.192. 2026-09-30 reported NAV 4.6207/1.1918; retrospective close/NAV ratios +0.006493% / +0.016781%; rounding envelopes [0.005410%,0.007575%] / [0.012585%,0.020978%]. Not IOPV, synchronous available quote, trade/arbitrage, independent upstream, historical vintage, or decision. Derived fields file SHA256 13a1c3a69dce4470ea267ce7024b47162f2dac78743a19e9eedb6ee4aac0da19 pinned; reobserve workflows now manual-only. Public executable commit 305ca72fe2b6cf1311c54dd3add7684745d0a43d, regression #45958774008 / job 140371375270: 1295 passed, 2 warnings, Ruff PASS; initial failure retained. No subsequent executable changes.
- Single-date frozen control: freeze original SHA256 1501bc46dc9fd0fbc5212ec774bee6759666162be469ff1d663ab1995204fd0b unchanged, original 45768518211/139735234269. Settlement code, tests, workflow and frozen blob match pre-maturity commit d6f9f10743ed765e7d3a5b4804650c8fc130b69b (2026-11-26). Marker history empty before activation. Actual 07:30:15 UTC after earliest 07:30:00 UTC, only marker added ccaf7f6b62fa80fbd8fdb5c01d3236da46cca871. First attempt #45958914319 / job 140371821872 success, 7 settlement tests passed; vendor query start 07:30:56.306451 UTC, observation 07:31:00.412896 UTC, 0 rows => UNAVAILABLE. Forecast UP, one frozen selected slot, 0 evaluable, coverage 0, accuracy null, bounds [0,1]. Not zero return or an incorrect forecast. Do NOT re-trigger, query alternate outcome, or backfill. Reason for missingness not established. Exact SHA256 outcome f25ec3d05cb8784583518a1c49f2a2152202fe25c439dd46b67cbcdbe43d8415 and assessment 0fd783854ecdbf5243ef86f18723f66912de8158cf77e6a8643c6c82353c4718 independently recomputed with original frozen bytes, exact rational forecast direction independently checked. Public archive commit 2e49f6c4298b80b4e5c8205e5668ba99d2bb18c3; private archive commit 2e28215f3b6d03edfb78483f502f48585d8777a0; frozen/outcome/assessment blobs identical across repos.
- Operational lesson: market maturity != provider readiness. Third-party documents report BaoStock daily K-line ingestion around 17:30 CST (https://github.com/Richeir/stock-db ; https://github.com/lzwme/finance-quant-skills/blob/main/skills/baostock/references/markdown/home.md); current provider page gives a platform-intro link but detailed exact update time could not be verified directly. This is a plausible scheduling risk, not confirmed cause of today’s missing outcome. For future cohort, propose first outcome activation no earlier than 18:00 CST (19:00 JST), inside existing maturity/deadline window; no change to registered protocol, target, strategy, source, no-backfill rule, or prior outcome. Operational timing proposal recorded now before cohort starts; do not start any automatic schedule or mutate frozen protocol. First cohort planning window 2026-11-29 CST, first target 11/30; no activation before window. Protocol blob c74bbd3fead2b7016bc64fb38c424677ba312042 unchanged.
- Formal RESEARCH BLOCK: historic source vintage/first availability, complete listing identity/corporate action coverage, actual costs/fills, independent source history remain missing. No model promotion, private gates NOT_RUN/BLOCKED_PUBLIC_ONLY_VALIDATION. Next Turn 04: do not repeat today’s ETF extraction or frozen settlement; focus actual evidence-to-decision usability and remaining admissibility gaps. Keep all unauthorized account/broker execution disabled. Do not start multi-day capture before its window; verify clock and first-attempt provenance.


## 2026-11-27 — current session Turn 04: constituent vintages and known symbol migration

- Public CSI300 fixed observation 45960676648/job140377481450: official notice passed; workbook parser blocked on exceptional SZSE 302132. First regression 45960676639/job140377481287: incorrect fixture SHA1 constant, 1 failed/1313 passed. Corrected replay 45961020301/job140378591352 at 3fbce084bee5261222a8fd3403e47f06666d011c pins all original first-capture SHA256, three external archive XLS and CSV Git blobs match and ordered codes identical. Workbook labels 2026-04-30,06-15,10-19 (archive filename days 05-06,06-16,10-20); each 300 distinct codes. June official 19 in/19 out exact set match; Jun-Oct 601059 out/002294 in. May/June external archive Actions run 25416636345/27598925909 corroborate commit chronology, logs HTTP410; Oct no run witness. No historical official availability or complete interval proof; no raw files retained. Official Nov26 member and Oct30 weight files same code set but mismatched labels: do not join as contemporaneous. Oct30 reported total99.990%, top10 22.664%, max600519 3.836%, effective count107.81. WARN only.
- Reviewed official notice 2025-028 and observed 45961469667/job140380038162 at 2bd6c534a7cbd1d83287737c6887f59bc7934920: 300114 ->302132 from 2025-02-17 open; issuer declares legal/share-count continuity at code change and prior major restructuring. PDF hash dd68049c48df826848f361fd9e7b23dd20b6805144a2e5bc36e54db638611488. All three new-code vendor requests return 5 pre +5 post sessions, identical normalized digest; Sina/Tencent old code five pre sessions match new-code overlapping closes, BaoStock old code query failed. No automatic history stitching or historical code validity from current vendor backfill. 
- Shared index_constituent_cohort guard selects one exact visible cohort (effective/available/ingested times and dataset source), rejects mixed sources, duplicates, unreconciled weight total; no older fill or fallback. Point-only, completeness false; per-row capture clocks/refs may conservatively block. Narrow known-code date guard blocks invalid ordinary capture and receipt replay windows, direct cash fee and joint scenario anchors; does not widen lot-rule prefix. Public final executable cd25677c4d61e32816e8fa60f8039dabe4133cce, regression 45961883426/job140381379585 **1346 passed, 2 warnings, Ruff pass**. Both observation workflows now manual-only (no push trigger). 
- Formal RESEARCH remains BLOCK: historical first availability, continuous membership/weights, complete security/listing and corporate action history, actual fees/fills, source independence, private gates not run. No accepted pin promotion, no Round4, no execution. Turn03 pilot is final UNAVAILABLE (no retry/alternate/backfill). Multi-day protocol unchanged, first planning window Nov29 CST, first target Nov30; no early activation. 
- Next Turn 05: do not repeat these fixed public observations. Prioritize remaining real evidence/admission gaps (especially official point-in-time identity/coverage and genuine account fee/fill evidence only when explicitly provided); do not create redundant synthetic validators or overstate data coverage. Use public compute only and real ~20 min clock/watchdog.



## 2026-11-27 — new session Turn 01 (17:07 JST): delisting, relisting, separate price reference and execution

- Opened 2026-11-27 17:07:40 JST, public-only compute and bounded workers. Previous handoff main 69165f4c346e8f725bdcbe87a879aa73675ff12c. No repetition of CSI300 or code migration controls.
- Public run 45963586265/job140386870379 at 6db8ebfc85f96069b4da5f7f62af1c0a34a7db36: five SSE notices independently retrieved and rehashed MATCH at parent. 600087 suspended 2013-05-14, termination decision 2014-04-11, last delisting-period day 2014-06-04, removal 2014-06-05; OTC 400061 reported start 2014-08-06, approval/reorganization 2018-11-02, new 601975 relisted 2019-01-08. Distinct listing life, not a continuous ordinary SSE series. Twelve narrow vendor windows: old-code correct window 2 days and new-code correct window 4 days, equal normalized digests across BaoStock/Sina/Tencent; wrong-code windows 4 empty/2 Sina ValueError. No positive incompatible observation; no source independence or original historical availability claim. WARN only.
- Supplement 45964067348/job140388442134 at dd9f3b0baba1fe7e296da10d49c128ebad95fddc: SSE education notice 20966 bytes SHA256 f8dd3f36a6e2db7a0b6fea397954c77e9f90d8f388e86b02e5e7ae489c615f55 parent rehash MATCH; no daily limit first session, two intraday halts 09:31–10:01 and 10:03–14:57 CST, reported restructuring surrender 50% named shareholder and 10% other small shareholders. Separate historical rule fetch URLError 12.647s, no retry; supplement overall BLOCK. Original composite booleans false due to missing second document, not contradiction of observed education notice; later code separates observed case from rule document.
- Issuer filed notice 临2018-089 45964357765/job140389368572 at 7003159f1d13c6bd5e7f5a3e223ab1a5d7e417f2: 20 pages, 519060 bytes SHA256 35a3788bc7b82b246dae44c08edf6445e528b1873fdaa83b653e247b36b91abd, parent + temporary rehash MATCH. Opening reference 4.31 CNY from issuer-reported OTC last close 2017-02-27, not executed open, no independent OTC quote proof. No first-day daily band, next-day declared 5%. 1,898,551,957 unrestricted (37.79%) + 3,124,848,067 restricted (62.21%) = 5,023,400,024 total; no individual entitlement inference. PDF archive path date 2018-12-28; machine signature date null; no first-availability proof. WARN.
- Daily status 45964994349/job140391449212 at 7b375fa57f51b0f207937cadb716a6b7e3f63326: BaoStock current listing reports ipoDate 2019-01-08, both raw sessions tradestatus=1/isST=1. Jan08 preclose 4.31 matches issuer, open 2.81 close 3.31; Jan09 preclose 3.31 and OHLC 3.14. Daily trading flag does not prove absence of intraday halts or fill; current listing row does not prove vintage. No raw provider body retained. WARN.
- Shared known-identity negative guard for 600087 end >= 2014-06-05 / 601975 start < 2019-01-08; acquisition and canonical receipt replay, fee/scenario and cash action audit/terms/parent+child acquisition. Separate ordinary daily cash guard also blocks 601975 first relisting session including warm-up; valid raw closing observation is not invalidated merely because trading is exceptional. Prior 300114/302132 guard preserved. No general listing universe or automatic identity stitching.
- Public final tested main f0764d9e3a21212ed2dab7e8a3e8ab73cfd06386, regression 45965141742/job140391919732 **1379 passed, 2 warnings, Ruff pass** (33 additional vs 1346). Retain intermediate Ruff failures 45964357701/job140389368646 (1376 tests passed, E731) and 45964485704/job140389789462 (1377 tests passed, I001); fixed, 45964739995/job140390623810 green, then 45964994310/job140391448768 green. Four observation workflows manual-only; no rerun for lint or missing historical rule. No accepted pin promotion.
- Formal RESEARCH BLOCK: first-availability history, full listing/corporate-action coverage, independently observed historical data, actual fees and fills remain unavailable. No private runtime admission or Round4, no account/broker action. Prior frozen single-day pilot final UNAVAILABLE; no retries/alternate/backfill; multi-day plan first planning Nov29 CST, first target Nov30, never early activate.
- Next session Turn 02: prioritize remaining material real evidence and formal admission prerequisites. Do not re-run these fixed relisting/corporate action observations, CSI300 or previous ETF/pilot observations. Do not manufacture actual account data or promote pin without verified admission. Public compute only, actual ~20 min and watchdog per task.


## 2026-11-27 session Turn 02 — fund dealing, historical PCF and time boundaries
- Fixed official CNINFO notice control 45966938768/job140397751052 WARN: four PDF parent-byte hashes verified. 159607 Sep7 primary both suspended/secondary reported allowed, planned Sep8 resume; 159696 Aug28 announced secondary halt until planned 10:30 CST, redemption reported allowed and creation unknown from notice alone; issuer Aug27 close 2.044 and IOPV 1.8392. 161907/015558 Aug11 CNY1m aggregate single account/day across classes/channels/subscription-conversion-in-periodic investment; contradictory exact-cap wording, above cap may reject; redemption and conversion-out reported allowed. May18 earlier cap removal does not establish current unlimited access.
- PCF archive: 45967473048/job140399511232 worker invocation failed all eight (workflow green, semantic BLOCK); corrected in 24a599c2276456e6d8b5b3e1f8dff55201f9b401. 45967529896/job140399697140 verified four pinned ZIP digests/sizes and exact matching official SZSE XML bytes; parse BLOCK on integral decimal lexical format. Fixed parser, pinned XML-only replay 45967672757/job140400171797 all four OBSERVED; no repeated ZIP download. 159607 Sep7 N/N NAV ref Sep3 0.7685, Sep8 Y/Y ref Sep4 0.7896; 159696 Aug27 Y/Y ref Aug25 1.8389, Aug28 Y/Y ref Aug26 1.8392. PCF is not same-day NAV or independent IOPV; raw limit semantics preserve zero as no numeric cap in that field, not unlimited acceptance. Third-party release publication Sep7 14:33 CST; other three after close. No pre-open first-availability claim. Source identity/hash matches are not independent evidence or full rule chain. No raw archive redistribution.
- Secondary close crosscheck 45968460838/job140402749575 WARN: Sina/Tencent 24 matched daily observations; fixed 159607 Sep7 .775/Sep8 .771, 159696 Aug27 2.044/Aug28 2.040 exact both providers; Aug27 matches issuer. No proof of intraday resume or fills.
- Shared scheduled_interval_visible and fund_dealing_guard: requires actual ingestion by cutoff; explicit per-direction PCF flags; prior session and same-day captured after query time not admitted as current; unknown account aggregate and exact ambiguous cap remain unknown, no inference of secondary access or acceptance.
- Final tested public head 5ba17493bd4d8c40fc8d894aad0245254538e4da, regression 45968665506/job140403422046: **1427 passed, 2 warnings, Ruff pass** (+48 vs 1379). Intermediate regression failures 45967473131/job140399511410 Ruff I001/UP017, 45967867025/job140400809613 pytest reserved parameter; corrected. All three new observation workflows returned to manual-only; no repeat fetch for lint. No accepted pin promotion.
- Formal RESEARCH still BLOCK: historical first availability, full coverage, independent historical sources, actual fees/fills and private runtime admission missing. Prior frozen pilot final UNAVAILABLE, no retry/fallback/backfill; Nov30 multi-day protocol first planning Nov29 CST, no early activation. No Round4/account/broker/credential action.
- Next Turn 03: prioritize remaining material evidence and formal admission boundaries; do not repeat fixed fund notices, PCF/close comparison, prior relisting, CSI300 or pilot observations. Public compute only, real ~20 min with task watchdogs.
