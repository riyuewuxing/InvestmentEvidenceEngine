# AGENTS.md｜InvestmentEvidenceEngine 硬规则

本文件对未来任何 AI、Codex、Copilot 或人工施工者生效。

## 1. 项目本质

`InvestmentEvidenceEngine` 是 `touzizhuanjia` 的公共证据获取与机械计算执行器，不是投资 AI，不是投资顾问，不是自动交易系统。

唯一正确关系：

`ChatGPT Commander -> ExecutionRequest -> InvestmentEvidenceEngine -> ExecutionResult/Artifacts -> 主项目 EvidenceAdmission`

Engine 负责观察、计算、渲染、测试和封装；解释与投资判断属于 Commander。

## 2. 永久禁止

- 禁止接收真实账户、真实持仓、成本价、现金余额、真实交易记录、broker account 或 private URI；
- 禁止输出 BUY/SELL/HOLD 或仓位建议；
- 禁止执行真实券商订单；
- 禁止把 scanner rank 描述为收益预测；
- 禁止把回测结果描述为未来收益保证；
- 禁止隐藏 provider 失败、冲突、缺失或 schema 漂移；
- 禁止历史请求使用未来才可获得的数据；
- 禁止仅凭 executor 声明的 hash 信任 artifact；
- 禁止长期提交大型行情缓存和临时中间数据。

## 3. 所有 worker 的统一合同

任何新 worker 必须：

1. 接受 `ExecutionOperation`；
2. `public_data_only=true`；
3. `decision_authority=false`；
4. 明确 `as_of`；
5. 保存来源/参数/时间边界；
6. 历史任务处理 PIT availability；
7. 失败时显式 `WARN/BLOCK/ERROR`；
8. 输出 artifact SHA256；
9. 可复现；
10. 只返回 evidence，不返回 recommendation。

## 4. 状态语义

- `PASS`：该 operation 的既定合同在本次真实执行中满足；
- `WARN`：结果可用但存在明确质量限制；
- `BLOCK`：缺关键证据、PIT 不安全、输入越界或完整性失败；
- `ERROR`：程序/环境异常；
- `PENDING`：尚未执行或依赖未完成。

代码存在不等于 PASS；测试文件存在不等于测试跑过。

## 5. Evidence worker 范围

一级 evidence domains：

- MARKET
- PRICE_STRUCTURE
- FUNDAMENTAL
- CORPORATE_EVENT
- OWNERSHIP_FLOW
- VALUATION
- INDUSTRY_MACRO
- RULE_IDENTITY

研究计算 operations：

- PIT_REPLAY
- FACTOR_COMPUTE
- BACKTEST
- OPPORTUNITY_SCAN
- PORTFOLIO_MATH
- TEST_SUITE

## 6. 来源纪律

优先级：官方披露/交易所/监管源 > 成熟结构化 provider > 第三方摘要。

市场数据应尽量双源交叉验证。第三方 provider 失败不得静默替换为伪造值。当前事实必须记录抓取时间；历史事实必须记录或验证 available_at。

## 7. PIT

历史 `as_of` 是硬边界。报告期、事件发生日、数据日期不等于“当时已经公开可知”。缺 verified availability 时必须 WARN 或 BLOCK，不能通过后见信息补齐历史。

## 8. GitHub Actions

Public 标准 runner 用于：依赖构建、公开数据抓取、回测、扫描、图形、测试和 artifact。大型 raw data 尽量只在 runner 临时磁盘存在。

workflow 不得把 secret 打进日志。Public workflow 不得 checkout 私有 `touzizhuanjia`。

## 9. 与主项目版本关系

每个结果必须绑定：

- subject_repo + subject_commit；
- executor_repo + executor_commit；
- trace_id；
- request_sha256；
- artifact_sha256；
- as_of。

executor commit 不要求等于 subject commit。

## 10. 开发规则

开始施工前读取：`AGENTS.md -> PROJECT_STATE.md -> PROJECT_ROADMAP.md -> NEXT_SESSION_PROMPT.md -> README.md`。

每轮结束必须同步 STATE、ROADMAP、NEXT。未真实运行的 worker 写 `IMPLEMENTED_NOT_RUNTIME_VALIDATED`，禁止写 PASS。
