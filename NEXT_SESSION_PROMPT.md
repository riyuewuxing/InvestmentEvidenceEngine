# NEXT_SESSION_PROMPT.md｜InvestmentEvidenceEngine 下一施工指令

更新时间：2026-09-02

## Authority

Canonical Engine repository：Public `riyuewuxing/InvestmentEvidenceEngine`。
Accepted executor snapshot：`86887ff40fee3166629f6e14d7531fe9542cc266`。
Private bootstrap 仅为历史迁移来源，不再作为 Engine 开发 authority。

## 接管读取顺序
1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `PROJECT_ROADMAP.md`
4. 本文件
5. `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md`
6. `README.md`
7. contracts / dispatch / workflows

## 已完成

Public regression、provider health、真实 `600519` execution、Public artifact 下载与 observed-byte SHA、private EvidenceAdmission/EvidenceGraph、Commander structural binding 已全部真实完成。不要重复建设独立仓或重新做第一次迁移。

## 下一大主线：E6 规模化与治理

优先顺序：

1. 用真实 Public runner 跑 representative `FACTOR_COMPUTE -> BACKTEST` benchmark，记录耗时、数据量、内存、成本假设和 provenance；
2. 跑 `OPPORTUNITY_SCAN` 全市场/大样本性能基准，决定 matrix/sharding 边界；
3. 加 provider rate-limit/backoff/schema-drift 监控；
4. 制定 raw data / artifact retention、数据许可与再分发边界；
5. 加 secret/dependency/SBOM 安全门；
6. 建立 Engine contract/version compatibility matrix；
7. 若工具支持，再创建 `v0.1.0` tag/release；否则继续以 accepted executor commit SHA pin。

任何施工结束仍必须更新 STATE / ROADMAP / NEXT，并保留 WARN/BLOCK 原始语义。
