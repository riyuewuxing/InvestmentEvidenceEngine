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

## 2026-11-24 visual QA checkpoint

Read `docs/PUBLIC_VISUAL_QA.md`. Public run `45369573507` proved desktop/mobile Chromium and native Windows actual screen capture; all PNGs independently hashed and viewed. Verify latest regression and use `visual_qa/verify_log.py` for subsequent log recovery. Product-specific integration requires approved public source/bundle or private/local runner. Do not claim private product screenshots or checkout private repo. Existing E6 tasks remain.


## 2026-11-26 valuation cutoff checkpoint

First check public engine-regression for the latest correction. Never relabel a date-filtered valuation series as PIT-safe; no known publication/revision vintage, no independent crosscheck. Existing accepted executor pin is not silently advanced. Only public independent Actions resources; never private checkout or runner. Do not transfer private opportunity-cost/admission logic or holdings into this repository.

## 2026-11-26 later checkpoint — current continuation

Read current public and private authority state and latest exact-SHA Actions logs; September acceptance is historical. Do not repeat the already observed full market scan, single-source cutoff smoke or failed BaoStock listing probe without new evidence. The real market control 45809117132 established 38 observed rows through the requested 2026-11-25 cutoff only; independent source and original/vintage bytes are still missing. Public scan attachment verification is now connected to runner; RESEARCH intentionally blocks pending real historical-vintage evidence and profile. Verify exact candidate bytes before using them. The frozen forward control must not run before its existing scheduled cutoff. Preserve original acceptance pin; do not restore private CI, disclose private state, or equate public unit tests with private acceptance. Next prioritize a verified independent provider / original capture receipt and truthful research execution; preserve prior successful scope.

## 2026-11-26 latest checkpoint

Use current exact SHA and completed logs. Tencent/Eastmoney 459-bar control and 38-bar production raw crosscheck already observed; do not rerun unchanged. SSE main/STAR compact date format observed successfully (1700/619); SZSE transport blocked. Do not blind retry or treat partial coverage as full. Conditional real scan never ran, packet replay synthetic only. Retrospective diagnostic is not PIT RESEARCH. Preserve historical acceptance pin, private dual gate BLOCK, and frozen prospective experiment. Resolve missing coverage/real candidate attachment and genuine PIT evidence before formal admission.
