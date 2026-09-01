# PROJECT_STATE.md｜InvestmentEvidenceEngine 当前状态

更新时间：2026-09-02
Canonical repository：Public `riyuewuxing/InvestmentEvidenceEngine`
迁移来源：private `riyuewuxing/touzizhuanjia@ccfcc2896407cac052192391144bae2ddc9ca28a` 的 `engine_bootstrap/InvestmentEvidenceEngine/`

## 结论

`IMPLEMENTATION=COMPLETE`  
`PREPUBLIC_RUNTIME=VALIDATED`  
`PUBLIC_REPOSITORY=CREATED`  
`PUBLIC_RUNTIME=ACTIVATING`

本仓已经由用户创建为独立 Public Engine。当前提交将 bootstrap 提升为仓库根目录 canonical implementation；正式 `PUBLIC_RUNTIME=VALIDATED` 必须等待本 Public repo 的 regression / provider health / real-company execution 实际跑通，并由 private 主项目重新按 artifact bytes/hash 准入。

## 职责边界

Engine 是非智能执行器：

- 只接收 sealed、public-data-only `ExecutionRequest`；
- 获取公共市场/公司/规则证据；
- 做确定性计算、回测、扫描、可视化和测试；
- seal `ExecutionResult` 与 artifacts；
- `decision_authority=false`；
- 不接 private account/holdings/cost basis/transactions；
- 不产生 BUY/SELL/HOLD；
- 不执行券商订单。

## 已实现 OperationKind

全部 15 类已接 dispatcher：

- MARKET_DATA
- PRICE_ANALYTICS
- KLINE_RENDER
- COMPANY_EVENT_TIMELINE
- FUNDAMENTAL_HISTORY
- VALUATION_HISTORY
- OWNERSHIP_FLOW
- INDUSTRY_MACRO
- OFFICIAL_SOURCE
- PIT_REPLAY
- FACTOR_COMPUTE
- BACKTEST
- OPPORTUNITY_SCAN
- PORTFOLIO_MATH
- TEST_SUITE

## 已验证的 pre-public 基线

Regression：private run `33530546493`，13 tests + Ruff PASS。

真实 `600519` vertical slice：private run `33531002571`，9 artifacts，0 missing，0 mismatch；EvidenceAdmission / EvidenceGraph / CommanderEvidenceSession / `DecisionMemo(conclusion=null)` graph binding 均通过。

这些证据只证明迁移来源质量，不能替代本 Public repo 的运行验收。

## 迁移时新增韧性

- SSE 保留跨栏目/镜像/附件 fallback；
- CSRC `公开募集证券投资基金运作管理办法` 增加证监会官方历史页面与官方 PDF fallback；
- provider-health 与真实 OFFICIAL_SOURCE worker 使用同一套 fallback + token 校验；
- GitHub official actions 升级到 Node 24 runtime major，业务 Python 仍为 3.11。

## 当前验收目标

1. Public regression：install / pytest / Ruff；
2. Public provider-health：市场 provider + SSE/SZSE/CSRC；
3. Public real-company `600519` execution；
4. 下载真实 Public artifact 并复算 SHA；
5. private `touzizhuanjia` 对 Public artifacts 做 EvidenceAdmission / EvidenceGraph；
6. 记录 `subject_repo+subject_commit` 与 `executor_repo+executor_commit`；
7. 再冻结 canonical/release 状态。

任何外部 provider 瞬态故障都必须显式 WARN/BLOCK，不允许伪造 PASS。
