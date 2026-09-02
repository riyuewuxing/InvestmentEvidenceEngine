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
- [ ] Git tag / GitHub Release（当前连接器无创建 tag/release 写动作；commit SHA 继续作为可复现 pin）
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
- [x] representative factor/backtest Public runtime benchmark — run `33618492904`
- [x] large-sample synthetic scanner capacity baseline（6k；12k four-way sharding）
- [ ] live real full-A-share public-data scanner performance acceptance
- [x] matrix/sharding foundation
- [x] bounded retry/degradation framework
- [ ] market-provider-specific rate-limit/retry policy where provider semantics justify it
- [x] data-license/redistribution initial review
- [x] source schema fingerprint/drift monitoring foundation
- [ ] reviewed persistent schema baseline promotion/alerting across multiple live snapshots
- [x] scheduled provider health
- [x] contract/version compatibility matrix
- [x] artifact retention / size policy hardening
- [x] security / secret hard gate
- [x] SBOM/dependency hard gate

Evidence:
- `docs/E6_RUNTIME_ACCEPTANCE.md`
- benchmark run `33618492904`
- provider/schema/retry run `33618698768`
- final regression run `33619173573`
- final security run `33619173578`

状态：`CORE_COMPLETE_LIVE_DISCOVERY_REMAINS`

## E7｜产品级跨仓验收支撑

Engine 侧下一任务不再横向增加指标，而是支持 private `touzizhuanjia` 的 V2-M5 产品级验收：

- [ ] real DISCOVERY case：真实市场 universe -> public evidence/scan -> private admission；
- [ ] RESEARCH case：mechanism/factor/backtest evidence -> private graph；
- [ ] PORTFOLIO case：仅主仓持有私人状态；Engine 只接公共/泛化计算请求；
- [ ] LEARNING case：历史 Decision/Outcome 在 private graph 中回放，Engine 只提供 PIT-safe external evidence；
- [ ] V1 legacy acceptance assumptions 与 V2 dual-provenance contract 最终对齐；
- [ ] product freeze 时固定新的 accepted executor commit。

状态：`NEXT`

## 当前优先级

进入跨仓产品级场景验收。首先补齐 **真实 DISCOVERY / 全市场扫描**，因为 synthetic capacity 已证明算力路径，但还没有证明 live public-data universe acquisition 和实际 discovery throughput。
