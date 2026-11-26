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
