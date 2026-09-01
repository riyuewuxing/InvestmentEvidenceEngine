# PROJECT_STATE.md｜InvestmentEvidenceEngine 当前状态

更新时间：2026-09-02
Canonical repository：Public `riyuewuxing/InvestmentEvidenceEngine`
Canonical implementation activation：`c55fcf744aacd71fb40214d408d790b369dc25a1`
Accepted executor snapshot：`86887ff40fee3166629f6e14d7531fe9542cc266`
Subject acceptance snapshot：private `riyuewuxing/touzizhuanjia@ccfcc2896407cac052192391144bae2ddc9ca28a`

## 当前结论

`IMPLEMENTATION=COMPLETE`
`PREPUBLIC_RUNTIME=VALIDATED`
`PUBLIC_REPOSITORY=CANONICAL`
`PUBLIC_REGRESSION=PASS`
`PUBLIC_PROVIDER_HEALTH=PASS`
`PUBLIC_VERTICAL_SLICE=PASS_WITH_EXPLICIT_WARNINGS`
`PRIVATE_CONSUMER_ADMISSION=PASS_WITH_EXPLICIT_WARNINGS`

Public Engine 已经真实独立运行，不再依赖 private `touzizhuanjia` checkout。

## Public runtime evidence

- Regression run `33536018264`: SUCCESS
- Provider-health run `33536018282`: SUCCESS
- Real `600519` execution run `33536165615`: SUCCESS
- Public execution commit `86887ff40fee3166629f6e14d7531fe9542cc266`
- Request SHA `a7993b6b05ea9d5e15580f5560962eb4d758462015b50c0cf7e8a3da713b5dd9`
- Result SHA `d1349e939235588a81f71cbcc41700b609780f07fbcad98132823221726ec5cd`
- Public artifact `9811857918`, ZIP digest `8c0bc02892747ad98a48f6df6a364b3ac5c35e0733bc5df62c413d83bd1c37fa`
- 9 declared artifacts, 0 missing, 0 observed-byte SHA mismatch.

## Private consumer evidence

Private subject runtime from fixed commit `ccfcc289...` re-read the downloaded Public bytes and ran production admission code:

- status `WARN`
- execution verified
- artifact integrity verified
- admissible for decision
- blockers 0
- Admission EvidenceGraph SHA `a14c67b43169c44bd1a16b01c7c31a4cce2677228f5f17652aa7dd6fcbd224e5`

Commander structural binding also passed with `conclusion=null`, `research_only=true`, `execution_allowed=false` and matching graph ID/SHA.

## WARN is intentional, not failure masking

The accepted real run contains transparent upstream degradation:

- AKShare used Sina fallback while BaoStock remained available for cross-check;
- current financial evidence warns that historical PIT availability requires separate validation;
- some industry Eastmoney endpoints were unavailable, benchmark fallback remained available;
- SSE and CSRC official fallback routes were used.

There were no BLOCK/ERROR operations. WARN must remain visible in downstream reasoning.

## Canonical responsibility

This repo owns public evidence acquisition, deterministic compute, charts, research calculations, source validation and sealed artifacts. It owns no AI decision authority, private portfolio state or broker execution.

See `docs/PUBLIC_RUNTIME_ACCEPTANCE_2026-09-02.md` for the acceptance record.
