# NEXT_SESSION_PROMPT.md｜InvestmentEvidenceEngine 下一施工指令

更新时间：2026-09-02

## Authority

Canonical Engine repository 已切换为 Public `riyuewuxing/InvestmentEvidenceEngine`。
private `riyuewuxing/touzizhuanjia/engine_bootstrap/InvestmentEvidenceEngine/` 只保留历史迁移来源语义，不再作为后续 Engine 开发 authority。

## 接管读取顺序

1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `PROJECT_ROADMAP.md`
4. 本文件
5. `README.md`
6. `src/investment_evidence_engine/contracts.py`
7. `src/investment_evidence_engine/dispatch.py`
8. `.github/workflows/`

## 当前施工点

独立 Public repo 已创建并正在首次 activation。下一目标不是重写 Engine，而是完成 Public 真验收：

1. Public regression；
2. provider health；
3. real `600519` sealed request；
4. artifact download + observed SHA；
5. private `touzizhuanjia` EvidenceAdmission / EvidenceGraph；
6. subject/executor 双 repo+commit provenance；
7. release/tag 与两仓状态冻结。

## 禁止

- 不让 Public workflow checkout private 主项目；
- 不向 Public payload 发送 private portfolio/account state；
- 不生成 BUY/SELL/HOLD；
- 不执行券商订单；
- 不把 WARN/BLOCK 改写成 PASS；
- 不用 pre-public run 冒充 Public acceptance。
