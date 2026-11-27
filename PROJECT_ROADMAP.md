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
