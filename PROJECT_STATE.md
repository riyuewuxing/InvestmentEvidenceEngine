# PROJECT_STATE.md｜InvestmentEvidenceEngine 当前状态

更新时间：2026-09-02
Canonical repository：Public `riyuewuxing/InvestmentEvidenceEngine`
Canonical implementation activation：`c55fcf744aacd71fb40214d408d790b369dc25a1`
First accepted real-company executor：`86887ff40fee3166629f6e14d7531fe9542cc266`
E6 accepted code/security snapshot：`b67c485d6c37b8b6e92bd44509ec5cec117b4512`
Subject acceptance snapshot：private `riyuewuxing/touzizhuanjia@ccfcc2896407cac052192391144bae2ddc9ca28a`

## 当前结论

`IMPLEMENTATION=COMPLETE`
`PUBLIC_REPOSITORY=CANONICAL`
`PUBLIC_VERTICAL_SLICE=PASS_WITH_EXPLICIT_WARNINGS`
`PRIVATE_CONSUMER_ADMISSION=PASS_WITH_EXPLICIT_WARNINGS`
`E6_SCALE_GOVERNANCE=PASS_WITH_SCOPE_LIMITS`
`NEXT_PRODUCT_MILESTONE=V2_M5_PRODUCT_GOVERNANCE_ACCEPTANCE`

Public Engine 已真实独立运行，不依赖 private `touzizhuanjia` checkout，也不拥有 AI 决策权。

## Public real-company evidence

- Regression run `33536018264`: SUCCESS
- Provider-health run `33536018282`: SUCCESS
- Real `600519` execution run `33536165615`: SUCCESS
- Public execution commit `86887ff40fee3166629f6e14d7531fe9542cc266`
- Request SHA `a7993b6b05ea9d5e15580f5560962eb4d758462015b50c0cf7e8a3da713b5dd9`
- Result SHA `d1349e939235588a81f71cbcc41700b609780f07fbcad98132823221726ec5cd`
- Public artifact `9811857918`, ZIP digest `8c0bc02892747ad98a48f6df6a364b3ac5c35e0733bc5df62c413d83bd1c37fa`
- 9 declared artifacts, 0 missing, 0 observed-byte SHA mismatch.

Private consumer re-read actual Public bytes and production admission returned:

- status `WARN`
- execution verified
- artifact integrity verified
- admissible for decision
- blockers 0
- Admission EvidenceGraph SHA `a14c67b43169c44bd1a16b01c7c31a4cce2677228f5f17652aa7dd6fcbd224e5`

Commander structural binding also passed with `conclusion=null`, `research_only=true`, `execution_allowed=false` and matching graph ID/SHA.

## E6 scale/compute runtime evidence

Research compute benchmark run `33618492904`: SUCCESS, all six matrix jobs passed.

Observed formal request-path benchmarks:

- baseline: 20,000 factor/backtest rows + 6,000 synthetic scanner rows; 0.411s; 153,924 KiB max RSS; PASS;
- representative: 50,000 rows + 6,000 scanner rows; 0.948s; 242,796 KiB; PASS;
- shard-0: 20,000 rows + 3,000 of a 12,000-row universe; 0.406s; 147,828 KiB; PASS;
- shard 0..3 all succeeded.

This proves deterministic capacity/sharding through the real `ExecutionRequest -> ExecutionResult` path. It does **not** equal a live full-A-share market scan.

## E6 provider/schema/retry evidence

Provider-health run `33618698768`: SUCCESS.

- AKShare primary source was unavailable during this snapshot and remained visible as BLOCK;
- BaoStock PASS, 33 rows;
- normalized OHLCV schema PASS;
- observed BaoStock schema fingerprint `72e44226bf43fa0daaf039da4821dc7e1bab991e51b70f26702bde63cdab0138`;
- SSE / SZSE / CSRC official sources 3/3 PASS;
- SSE used official fallbacks;
- CSRC recovered after one bounded timeout retry.

Schema fingerprints are observations, not auto-promoted permanent truth. Missing required normalized fields remain BLOCK.

## E6 security / supply chain

Final security run `33619173578`: SUCCESS.
Artifact `9842203475`: `sha256:011cc30a0b210b7792f6464455727411df719db9467282ad4de829f45dd1426e`.

Final hard gate:

- untriaged secret findings: 0;
- pip-audit exit code: 0;
- dependency vulnerabilities: 0;
- audited dependencies: 94;
- CycloneDX SBOM components: 94.

Final branch regression run `33619173573`: SUCCESS, 19 tests + Ruff PASS.

## E6 governance now implemented

- [x] formal factor/backtest/scanner benchmark harness;
- [x] deterministic matrix/sharding foundation;
- [x] schema fingerprint / drift guard;
- [x] bounded retry framework and official-source integration;
- [x] provider degradation remains explicit;
- [x] conservative data-license / redistribution policy;
- [x] short artifact-retention policy;
- [x] secret scan hard gate;
- [x] dependency vulnerability hard gate;
- [x] CycloneDX SBOM;
- [x] contract compatibility matrix.

## Intentional remaining limits

- [ ] real full-A-share public-data discovery/scanner throughput acceptance;
- [ ] reviewed persistent schema baseline promotion/alerting across multiple live snapshots;
- [ ] Git tag/release surface when a supported write tool exists.

These are not to be silently marked complete from synthetic benchmarks.

## Canonical responsibility

This repo owns public evidence acquisition, deterministic compute, charts, research calculations, source validation, benchmark/security infrastructure and sealed artifacts.

It owns no AI decision authority, private portfolio state or broker execution.

See:
- `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md`
- `docs/E6_RUNTIME_ACCEPTANCE.md`
- `docs/E6_SCALE_GOVERNANCE.md`
- `docs/DATA_LICENSE_AND_RETENTION_POLICY.md`
- `docs/CONTRACT_COMPATIBILITY.md`
