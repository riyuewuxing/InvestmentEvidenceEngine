# NEXT_SESSION_PROMPT.md｜InvestmentEvidenceEngine 下一施工指令

更新时间：2026-09-04

## Authority

Canonical Engine repository：Public `riyuewuxing/InvestmentEvidenceEngine`。
Private bootstrap 仅为历史迁移来源，不再作为 Engine 开发 authority。

## 接管读取顺序
1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `PROJECT_ROADMAP.md`
4. 本文件
5. `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md`
6. `docs/E6_RUNTIME_ACCEPTANCE.md`
7. `docs/E6_SCALE_GOVERNANCE.md`
8. `docs/DATA_LICENSE_AND_RETENTION_POLICY.md`
9. `docs/CONTRACT_COMPATIBILITY.md`
10. contracts / dispatch / workflows

## 已完成，不得重做

- Public canonical Engine 独立化；
- real `600519` Public vertical slice；
- private observed-byte hash admission / EvidenceGraph / Commander structural binding；
- 当前 accepted Gate1 executor 已登记并 dispatch 16 个 operation kind；后续文档提交不是 executor pin；
- FACTOR_COMPUTE -> BACKTEST -> OPPORTUNITY_SCAN formal benchmark；
- 6-job Public benchmark matrix；
- 12k synthetic universe four-way sharding foundation；
- schema fingerprint/drift guard；
- bounded official-source retry；
- data license / artifact retention policy；
- contract compatibility matrix；
- zero-untriaged-secret + zero-pip-audit-vulnerability hard gate；
- CycloneDX SBOM；
- 19 tests + Ruff final regression。

E6 detailed evidence：`docs/E6_RUNTIME_ACCEPTANCE.md`。

## 当前必须保持的事实

Synthetic capacity benchmark 不等于 live full-market acceptance。

当前仍未完成：

1. M5 product freeze 及更大规模 real full-A-share discovery throughput evidence；
2. multi-snapshot reviewed schema baseline promotion/alerting；
3. provider-specific rate-limit/retry only where upstream semantics justify it；
4. Git tag/release if a supported write surface becomes available。

`MARKET_UNIVERSE` 当前状态为 `IMPLEMENTATION_COMPLETE / LOCAL_TESTS_PASS / LIVE_PROBE_PASS_WITH_EXPLICIT_WARNINGS`；
Gate1 为 `PASS_WITH_EXPLICIT_WARNINGS`，M5 overall 为 `ACCEPTANCE_PENDING`。accepted executor
为 `1161a8a91657b4d1e4719e513025956b1720938c`，subject 为
`c4525244b250042e360b3cd55f3657ca89a1a5d6`；`main` 仍为
`db41a018447977e2203aed61239892dfbefbe1ac`。同一 executor 的 Engine
`33852576973`、Execute `33852576917`、Provider `33852576932`、Security `33852576906`
均 SUCCESS。远端 universe 报告 5555 rows、`WARN`；AKShare EM primary 失败，paged Sina
fallback 成功，listing unavailable，quote date UNKNOWN；下游 scan 为 `WARN`，含
`OPPORTUNITY_SCAN_DEPENDENCY_WARN`（20 candidates、2 rules）。Private admission 为
WARN/verified/integrity verified/admissible，tamper case 为 BLOCK。不要把 document follow-up
commit 当作 executor pin，也不要把 retrieval time 当作行情生效时间。下一步应完成 M5
product freeze、扩大 throughput 证据，并持续保留 provider WARN/BLOCK。

前一轮 monolithic Sina fallback 的 `JSONDecodeError` 已由有界逐页重试修复。Provider health
总体 SUCCESS 但 AKShare daily 仍记录 BLOCK (`RemoteDisconnected`)，BaoStock PASS 33 rows；
Security triage PASS（5 sealed ignored、unexpected 0、vulnerabilities 0）。Gate1 evidence
及完整 artifact hashes 见 `docs/V2_M5_GATE1_RUNTIME_ACCEPTANCE_2026-09-04.md`。

## 下一主线：配合 private V2-M5 产品级验收

优先顺序：

1. **DISCOVERY**：设计并真实运行 live public-market universe -> public evidence/features -> OPPORTUNITY_SCAN -> compact artifacts；
2. private `touzizhuanjia` 下载实际 Public bytes，执行 EvidenceAdmission；
3. **RESEARCH**：选一个机制/因子，跑 PIT-safe evidence -> factor -> backtest -> graph；
4. **PORTFOLIO**：验证私人账户数据始终留在 private repo，Public Engine 仅接公共或 generic/synthetic computation；
5. **LEARNING**：历史 Decision/Outcome 在 private graph 中 replay，外部 evidence 必须遵守 historical as-of/PIT；
6. 对齐 legacy V1 14-gate 与 V2 subject/executor dual provenance；
7. product freeze 时记录新的 accepted executor commit。

## 禁止回退

- 不重新把 private bootstrap 设为 canonical；
- 不把 synthetic scanner benchmark 描述成真实全市场发现能力；
- 不隐藏 provider/schema/security WARN/BLOCK；
- 不让 Public Engine 接触 holdings/cost basis/cash/transactions；
- 不在 Engine 内新增 LLM/投资判断；
- 不启用真实券商自动执行；
- 不用 branch name 代替 executor commit provenance。
