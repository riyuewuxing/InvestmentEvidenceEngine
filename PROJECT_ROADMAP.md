# PROJECT_ROADMAP.md｜InvestmentEvidenceEngine 路线图

更新时间：2026-09-02

## E0｜职责与合同

- [x] 无 AI / 无投资判断权；
- [x] public-data-only；
- [x] ExecutionRequest / ExecutionResult；
- [x] artifact provenance；
- [x] subject/executor 双 commit；
- [x] PIT / failure / UNKNOWN 纪律。

状态：`COMPLETE`

## E1｜公共证据 acquisition

- [x] 8 个一级 evidence domains；
- [x] resilient market multi-upstream；
- [x] provider cross-check；
- [x] historical fundamental PIT guard；
- [x] official-source fallback + token validation；
- [x] SSE 多官方路径韧性；
- [x] CSRC 多官方路径韧性。

状态：`IMPLEMENTED`

## E2｜研究计算资源

- [x] PIT_REPLAY；
- [x] FACTOR_COMPUTE；
- [x] BACKTEST；
- [x] OPPORTUNITY_SCAN；
- [x] PORTFOLIO_MATH；
- [x] TEST_SUITE；
- [x] scanner 仅 research-priority semantics；
- [x] portfolio math 仅 generic/synthetic。

状态：`IMPLEMENTED_UNIT_TESTED`

## E3｜独立 Public 仓

- [x] 创建 Public `riyuewuxing/InvestmentEvidenceEngine`；
- [x] bootstrap 迁到 repo root；
- [x] canonical implementation 切到独立仓；
- [x] regression workflow；
- [x] provider-health workflow；
- [x] execute-request workflow；
- [x] `repository_dispatch: execute-evidence-request`；
- [x] sealed/public-only firewall；
- [ ] release/version/tag。

状态：`PUBLIC_ACTIVATION_IN_PROGRESS`

## E4A｜Pre-Public GitHub-hosted runtime

- [x] regression 13 tests + Ruff；
- [x] real `600519` acquisition/compute/render；
- [x] 9 artifacts byte re-hash；
- [x] EvidenceAdmission / EvidenceGraph；
- [x] CommanderEvidenceSession / DecisionMemo graph binding。

Evidence：private runs `33530546493`, `33531002571`。

状态：`PASS_PREPUBLIC`

## E4B｜Public runner 真验收

- [ ] install / pytest / ruff；
- [ ] provider acquisition / cross-check；
- [ ] official source 3/3；
- [ ] Kline artifacts；
- [ ] artifact upload/download；
- [ ] private consumer admission；
- [ ] subject/executor 双 provenance；
- [ ] release pin。

状态：`RUNNING_NEXT`

## E5｜Public Vertical Slice

- [ ] sealed real-company request；
- [ ] Public executor repo/commit；
- [ ] Public Actions artifact；
- [ ] observed artifact SHA verification；
- [ ] private EvidenceAdmission；
- [ ] private EvidenceGraph；
- [ ] Commander structural binding。

状态：`PENDING_PUBLIC_RUN`

## E6｜规模化与治理

- [ ] representative factor/backtest Public runtime benchmark；
- [ ] full-market scanner performance；
- [ ] matrix/sharding；
- [ ] rate-limit/backoff/degradation；
- [ ] data-license/redistribution review；
- [ ] source schema drift monitoring；
- [ ] scheduled provider health；
- [ ] release compatibility matrix；
- [ ] artifact retention / size policy；
- [ ] security / secret scan；
- [ ] SBOM/dependency policy。

状态：`PENDING_PUBLIC_ACCEPTANCE`
